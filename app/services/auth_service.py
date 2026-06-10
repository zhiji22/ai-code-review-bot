"""
Auth service — JWT tokens, GitHub OAuth flow, user management.

 DESIGN.md §15 (Security) + §6 (Auth endpoints)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)


class GitHubOAuthResult(TypedDict):
    """Return type for github_oauth_exchange."""

    user: User
    github_token: str
    github_data: dict[str, Any]


class AuthService:
    """JWT issuance, GitHub OAuth, user CRUD."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ JWT
    @staticmethod
    def create_access_token(user_id: int, extra: dict[str, Any] | None = None) -> str:
        """Create short-lived access token (15min per §15)."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_access_expire_minutes),
            "type": "access",
            **(extra or {}),
        }
        return jwt.encode(payload, settings.secret_key, algorithm="HS256")

    @staticmethod
    def create_refresh_token(user_id: int) -> str:
        """Create long-lived refresh token (7d per §15)."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(days=settings.jwt_refresh_expire_days),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.secret_key, algorithm="HS256")

    @staticmethod
    def decode_token(token: str) -> dict[str, Any]:
        """Decode + verify JWT. Raises jwt.PyJWTError on invalid."""
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
        )

    # ------------------------------------------------------------------ GitHub OAuth
    async def github_oauth_exchange(
        self,
        code: str,
        state: str | None,
    ) -> GitHubOAuthResult:
        """Exchange GitHub OAuth code for access token + user info.

        Note: GitHub OAuth codes are single-use. The retry below only helps for
        connection-level failures that never reached GitHub's server. If the first
        attempt succeeded at GitHub's side but the response was lost, the retry
        will fail with a ``bad_verification_code`` error.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            # Exchange code → access_token (with retry for unstable networks)
            logger.info("GitHub OAuth: exchanging code for access token")
            exchange_payload = {
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            }
            # Only include state if non-null to avoid sending "state": null
            if state is not None:
                exchange_payload["state"] = state

            token_data: dict[str, Any] = {}
            for attempt in range(3):
                try:
                    token_resp = await client.post(
                        "https://github.com/login/oauth/access_token",
                        json=exchange_payload,
                        headers={"Accept": "application/json"},
                    )
                    token_resp.raise_for_status()
                    token_data = token_resp.json()
                    break
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
                    logger.warning(
                        "GitHub OAuth exchange attempt %d failed (network): %s",
                        attempt + 1,
                        exc,
                    )
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2.0 * (attempt + 1))

            logger.info("GitHub OAuth: token response keys=%s", list(token_data.keys()))

            if "error" in token_data:
                error_msg = token_data.get("error_description", token_data["error"])
                logger.warning(
                    "GitHub OAuth token error: %s — %s body=%s",
                    token_data["error"],
                    error_msg,
                    token_data,
                )
                raise ValueError(f"GitHub OAuth error: {token_data['error']} — {error_msg}")

            access_token = token_data.get("access_token")
            if not access_token:
                raise ValueError("GitHub OAuth: no access_token returned")

            # Get user info
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            user_resp.raise_for_status()
            gh_user = user_resp.json()

        # Upsert user
        user = await self._upsert_user(gh_user, access_token)
        return {
            "user": user,
            "github_token": access_token,
            "github_data": gh_user,
        }

    async def _upsert_user(
        self,
        gh_data: dict[str, Any],
        access_token: str,
    ) -> User:
        """Create or update user from GitHub data."""
        github_id = gh_data["id"]
        result = await self.session.execute(
            select(User).where(User.github_id == github_id)
        )
        user = result.scalar_one_or_none()

        if user:
            # Update existing
            user.username = gh_data.get("login", user.username)
            user.email = gh_data.get("email") or user.email
            user.avatar_url = gh_data.get("avatar_url", user.avatar_url)
            user.name = gh_data.get("name") or user.name
            user.bio = gh_data.get("bio") or user.bio
            user.company = gh_data.get("company") or user.company
            user.location = gh_data.get("location") or user.location
            user.github_access_token = access_token
            user.last_login_at = datetime.now(timezone.utc)
        else:
            # Create new
            user = User(
                github_id=github_id,
                username=gh_data["login"],
                email=gh_data.get("email"),
                avatar_url=gh_data.get("avatar_url"),
                name=gh_data.get("name"),
                bio=gh_data.get("bio"),
                company=gh_data.get("company"),
                location=gh_data.get("location"),
                github_access_token=access_token,
                last_login_at=datetime.now(timezone.utc),
            )
            self.session.add(user)

        await self.session.commit()
        await self.session.refresh(user)
        return user

    # ------------------------------------------------------------------ user helpers
    async def get_user_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_github_id(self, github_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.github_id == github_id)
        )
        return result.scalar_one_or_none()
