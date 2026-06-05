"""FastAPI dependency functions for auth, DB, pagination."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User
from app.services.auth_service import AuthService

settings = get_settings()


def _make_dev_user(user_id: int = 1) -> Any:
    """Create a lightweight dev user object (duck-typed, no SQLAlchemy needed)."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=user_id,
        github_id=999_999,
        username="dev_user",
        email="dev@test.com",
        avatar_url=None,
        name="Dev User",
        bio="Local development user",
        company=None,
        location=None,
        github_access_token=None,
        is_active=True,
        is_admin=True,
        last_login_at=now,
        created_at=now,
        updated_at=now,
    )


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: str | None = Header(None),
) -> User:
    """Extract and validate JWT token from Authorization header.

    In development mode, if the DB is unreachable, synthesizes a dev user
    from the JWT payload so the frontend stays usable without PostgreSQL.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()
    auth_service = AuthService(db)

    try:
        payload = auth_service.decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload.get("sub", 0))

    # Try DB first; fall back to synthesized dev user in development
    try:
        user = await auth_service.get_user_by_id(user_id)
    except Exception:
        if settings.app_env == "development":
            user = None  # DB unreachable, use fallback below
        else:
            raise

    if user is None and settings.app_env == "development":
        user = _make_dev_user(user_id)

    if user is None or not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
