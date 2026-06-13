"""Pydantic v2 schemas for rules API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RuleSchema(BaseModel):
    """Full rule output."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: str
    name: str
    description: str | None = None
    category: str
    severity: str
    pattern: str | None = None
    message: str
    suggestion: str | None = None
    languages: list[str] = Field(default_factory=list)
    enabled: bool = True
    is_builtin: bool = True
    repository_id: int | None = None
    created_at: datetime
    updated_at: datetime


class RuleListSchema(BaseModel):
    """Lightweight rule for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: str
    name: str
    category: str
    severity: str
    enabled: bool = True
    is_builtin: bool = True


class RuleCreateSchema(BaseModel):
    """Create custom rule."""

    rule_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(..., pattern=r"^(security|performance|style|best_practices)$")
    severity: str = Field(..., pattern=r"^(critical|warning|info)$")
    pattern: str
    message: str
    suggestion: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["python"])
    enabled: bool = True
    repository_id: int | None = None


class RuleUpdateSchema(BaseModel):
    """Update rule."""

    name: str | None = None
    description: str | None = None
    severity: str | None = Field(default=None, pattern=r"^(critical|warning|info)$")
    pattern: str | None = None
    message: str | None = None
    suggestion: str | None = None
    languages: list[str] | None = None
    enabled: bool | None = None


__all__ = [
    "RuleCreateSchema",
    "RuleListSchema",
    "RuleSchema",
    "RuleUpdateSchema",
]
