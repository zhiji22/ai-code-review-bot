"""Pydantic v2 schemas for repositories API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RepositorySettingsSchema(BaseModel):
    """User-configurable repo settings (JSONB)."""

    auto_review: bool = True
    languages: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    severity_threshold: str = "warning"  # minimum severity to post comment
    max_files_per_review: int = 100
    enable_llm: bool = True
    enable_ast: bool = True
    enable_rules: bool = True
    custom_rules_only: bool = False


class RepositorySchema(BaseModel):
    """Full repository output."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    github_repo_id: int
    full_name: str
    owner: str
    name: str
    description: str | None = None
    language: str | None = None
    default_branch: str | None = None
    is_private: bool = False
    is_active: bool = True
    installation_id: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    last_review_at: datetime | None = None
    total_reviews: int = 0
    created_at: datetime
    updated_at: datetime


class RepositoryListSchema(BaseModel):
    """Lightweight repo for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    owner: str
    name: str
    language: str | None = None
    is_private: bool = False
    is_active: bool = True
    total_reviews: int = 0
    last_review_at: datetime | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class RepositoryUpdateSchema(BaseModel):
    """Update repo settings."""

    is_active: bool | None = None
    settings: RepositorySettingsSchema | None = None


class RepositoryCreateSchema(BaseModel):
    """Schema for registering a new repository."""

    github_repo_id: int
    full_name: str
    owner: str
    name: str
    description: str | None = None
    language: str | None = None
    default_branch: str | None = "main"
    is_private: bool = False
    installation_id: int | None = None
    webhook_secret: str | None = None


__all__ = [
    "RepositoryCreateSchema",
    "RepositorySettingsSchema",
    "RepositorySchema",
    "RepositoryListSchema",
    "RepositoryUpdateSchema",
]
