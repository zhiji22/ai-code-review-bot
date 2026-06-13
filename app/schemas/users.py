"""Pydantic v2 schemas for user/auth API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserSchema(BaseModel):
    """User info."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    github_id: int
    username: str
    email: EmailStr | None = None
    avatar_url: str | None = None
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    location: str | None = None
    is_active: bool = True
    is_admin: bool = False
    last_login_at: datetime | None = None
    created_at: datetime


class TokenSchema(BaseModel):
    """JWT token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 min


class TokenRefreshSchema(BaseModel):
    """Refresh token request."""

    refresh_token: str


class GitHubLoginSchema(BaseModel):
    """GitHub OAuth callback."""

    code: str
    state: str | None = None
    redirect_uri: str | None = None


class GitHubLoginResponseSchema(BaseModel):
    """GitHub OAuth login response — tokens + user profile."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 min
    user: UserSchema


__all__ = [
    "GitHubLoginResponseSchema",
    "GitHubLoginSchema",
    "TokenRefreshSchema",
    "TokenSchema",
    "UserSchema",
]
