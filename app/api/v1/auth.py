"""Authentication endpoints — GitHub OAuth flow + dev login."""

from __future__ import annotations

import logging
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit
from app.models.user import User

from fastapi import Request
from app.schemas.common import ApiResponse
from app.schemas.users import (
    GitHubLoginResponseSchema,
    GitHubLoginSchema,
    TokenRefreshSchema,
    TokenSchema,
    UserSchema,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


@router.post(
    "/dev-login",
    response_model=ApiResponse[TokenSchema],
    summary="Dev-only login (returns JWT without DB)",
)
async def dev_login() -> ApiResponse[TokenSchema]:
    """Development-only endpoint: returns JWT for a built-in dev user.

    No database required — the user identity lives entirely in the JWT.
    Only available when APP_ENV=development.
    """
    if settings.app_env != "development":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev login only available in development mode",
        )

    # Dev user gets ID=1 — get_current_user will synthesize a User for this ID
    access = AuthService.create_access_token(
        1,
        extra={
            "username": "dev_user",
            "email": "dev@test.com",
            "is_admin": True,
        },
    )
    refresh = AuthService.create_refresh_token(1)

    return ApiResponse(
        data=TokenSchema(
            access_token=access,
            refresh_token=refresh,
            token_type="bearer",
            expires_in=settings.jwt_access_expire_minutes * 60,
        )
    )


@router.post(
    "/guest-login",
    response_model=ApiResponse[GitHubLoginResponseSchema],
    summary="Login as guest (demo account)",
)
async def guest_login(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[GitHubLoginResponseSchema]:
    """Login as a guest user using a predefined GitHub account.

    This allows visitors to explore the app without GitHub OAuth.
    The guest account credentials are configured via GUEST_GITHUB_TOKEN env var.
    """
    # Rate limit: 10 requests per minute per IP to prevent abuse
    client_ip = request.client.host if request.client else "unknown"
    await check_rate_limit(f"guest_login:{client_ip}", limit=10, window_seconds=60)

    service = AuthService(db)
    try:
        result = await service.guest_login()
    except ValueError as exc:
        logger.warning("Guest login rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Guest login failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Guest login failed. Please try again later.",
        ) from exc

    user: User = result["user"]
    access = AuthService.create_access_token(
        user.id,
        extra={
            "username": user.username,
            "email": user.email or "",
            "is_admin": user.is_admin,
        },
    )
    refresh = AuthService.create_refresh_token(user.id)

    return ApiResponse(
        data=GitHubLoginResponseSchema(
            access_token=access,
            refresh_token=refresh,
            token_type="bearer",
            expires_in=settings.jwt_access_expire_minutes * 60,
            user=UserSchema.model_validate(user, from_attributes=True),
        )
    )


@router.post(
    "/github",
    response_model=ApiResponse[GitHubLoginResponseSchema],
    summary="Login with GitHub OAuth code",
)
async def github_login(
    payload: GitHubLoginSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[GitHubLoginResponseSchema]:
    """Exchange GitHub OAuth code for JWT tokens + user profile."""
    service = AuthService(db)
    try:
        result = await service.github_oauth_exchange(
            payload.code,
            state=payload.state,
            redirect_uri=payload.redirect_uri,
        )
    except ValueError as exc:
        # GitHub returned an explicit error (bad code, expired, etc.)
        logger.warning("GitHub OAuth exchange rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub authentication failed. Please try again.",
        ) from exc
    except Exception as exc:
        logger.exception("GitHub OAuth exchange failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GitHub authentication failed. Please try again.",
        ) from exc

    user: User = result["user"]
    access = AuthService.create_access_token(
        user.id,
        extra={
            "username": user.username,
            "email": user.email or "",
            "is_admin": user.is_admin,
        },
    )
    refresh = AuthService.create_refresh_token(user.id)

    return ApiResponse(
        data=GitHubLoginResponseSchema(
            access_token=access,
            refresh_token=refresh,
            token_type="bearer",
            expires_in=settings.jwt_access_expire_minutes * 60,
            user=UserSchema.model_validate(user, from_attributes=True),
        )
    )


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenSchema],
    summary="Refresh access token",
)
async def refresh_token(
    payload: TokenRefreshSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TokenSchema]:
    service = AuthService(db)
    try:
        token_payload = service.decode_token(payload.refresh_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc
    user_id = int(token_payload["sub"])
    user = await service.get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    access = service.create_access_token(user.id)
    refresh = service.create_refresh_token(user.id)
    return ApiResponse(
        data=TokenSchema(
            access_token=access,
            refresh_token=refresh,
            token_type="bearer",
            expires_in=settings.jwt_access_expire_minutes * 60,
        )
    )


@router.get(
    "/me",
    response_model=ApiResponse[UserSchema],
    summary="Get current user",
)
async def get_me(
    current_user: CurrentUser,
) -> ApiResponse[UserSchema]:
    """Get the authenticated user's profile."""
    return ApiResponse(data=UserSchema.model_validate(current_user, from_attributes=True))
