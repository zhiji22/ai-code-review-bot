"""Pydantic v2 schemas for reviews API.

Per DESIGN.md §6: unified {data, meta} envelope, cursor pagination.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReviewCommentSchema(BaseModel):
    """Schema for review comment output."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_path: str
    line_number: int
    line_end: int | None = None
    source: str
    category: str
    severity: str
    message: str
    suggestion: str | None = None
    rule_id: str | None = None
    confidence: float = 1.0
    issue_type: str | None = None
    matched_text: str | None = None


class ReviewScoresSchema(BaseModel):
    """Schema for multi-dimensional scores."""

    overall: float | None = None
    security: float | None = None
    performance: float | None = None
    maintainability: float | None = None


class ReviewSchema(BaseModel):
    """Full review output."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    pr_number: int
    commit_sha: str
    pr_title: str | None = None
    pr_author: str | None = None
    status: str
    trigger: str

    overall_score: float | None = None
    security_score: float | None = None
    performance_score: float | None = None
    maintainability_score: float | None = None

    files_reviewed: int = 0
    files_total: int = 0
    lines_of_code: int = 0
    additions: int = 0
    deletions: int = 0

    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    llm_model: str | None = None
    llm_tokens_total: int = 0
    llm_cost_usd: float = 0.0
    duration_ms: int | None = None

    summary: str | None = None
    pr_comment_posted: bool = False
    inline_comments_posted: int = 0
    error_message: str | None = None

    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    comments: list[ReviewCommentSchema] = Field(default_factory=list)


class ReviewListSchema(BaseModel):
    """Lightweight review for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pr_number: int
    pr_title: str | None = None
    pr_author: str | None = None
    commit_sha: str
    status: str
    overall_score: float | None = None
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    duration_ms: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class ReviewCreateSchema(BaseModel):
    """Trigger manual review."""

    repository_id: int
    repository_full_name: str = ""
    pr_number: int
    commit_sha: str | None = None
    pr_title: str | None = None
    pr_author: str | None = None


class ReviewFiltersSchema(BaseModel):
    """Query filters for review listing."""

    repository_id: int | None = None
    pr_number: int | None = None
    status: str | None = None
    author: str | None = None
    min_score: float | None = None
    max_score: float | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort_by: str = "created_at"
    sort_order: str = "desc"
    cursor: str | None = None
    offset: int = 0
    limit: int = Field(default=20, ge=1, le=100)


__all__ = [
    "ReviewCommentSchema",
    "ReviewScoresSchema",
    "ReviewSchema",
    "ReviewListSchema",
    "ReviewCreateSchema",
    "ReviewFiltersSchema",
]
