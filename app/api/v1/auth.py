"""Authentication endpoints — GitHub OAuth flow + dev login."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.users import (
    GitHubLoginSchema,
    TokenRefreshSchema,
    TokenSchema,
    UserSchema,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


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

    auth = AuthService.__new__(AuthService)
    # Dev user gets ID=1 — get_current_user will synthesize a User for this ID
    access = AuthService.create_access_token(1, extra={
        "username": "dev_user",
        "email": "dev@test.com",
        "is_admin": True,
    })
    refresh = AuthService.create_refresh_token(1)

    return ApiResponse(
        data=TokenSchema(
            access_token=access,
            refresh_token=refresh,
            token_type="bearer",
            expires_in=900,
        )
    )


@router.post(
    "/github",
    response_model=ApiResponse[TokenSchema],
    summary="Login with GitHub OAuth code",
)
async def github_login(
    payload: GitHubLoginSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[TokenSchema]:
    """Exchange GitHub OAuth code for JWT tokens."""
    service = AuthService(db)
    try:
        tokens = await service.github_oauth_exchange(payload.code, payload.state)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"GitHub OAuth failed: {exc}",
        ) from exc
    return ApiResponse(data=tokens)


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
    user_id = service.decode_token(payload.refresh_token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
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
            expires_in=900,
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
