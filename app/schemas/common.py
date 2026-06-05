"""
Unified response/error schemas.

Per DESIGN.md §6: Standard JSON envelope {data, meta} + error format.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """Pagination and response metadata."""

    total: int | None = None
    page: int | None = None
    page_size: int | None = None
    has_next: bool | None = None
    cursor: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Standard API success response envelope."""

    data: T
    meta: ResponseMeta | None = None


class ErrorDetail(BaseModel):
    """Error detail structure."""

    field: str | None = None
    message: str
    code: str | None = None


class ErrorResponse(BaseModel):
    """Standard API error response."""

    error: ErrorDetail
    meta: ResponseMeta | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response with items list."""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    cursor: str | None = None
    next_cursor: str | None = None


class CursorPaginationMeta(BaseModel):
    """Cursor-based pagination metadata."""

    has_next: bool = False
    next_cursor: str | None = None
    limit: int = 20


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    service: str = "ai-code-review-bot"
    version: str | None = None
