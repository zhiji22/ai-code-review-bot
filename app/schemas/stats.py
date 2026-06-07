"""Pydantic v2 schemas for stats/dashboard API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class OverviewStatsSchema(BaseModel):
    """Dashboard overview stats."""

    total_reviews: int = 0
    total_repositories: int = 0
    total_issues: int = 0
    critical_issues: int = 0
    warning_issues: int = 0
    info_issues: int = 0
    avg_overall_score: float = 0.0
    avg_security_score: float = 0.0
    avg_performance_score: float = 0.0
    avg_maintainability_score: float = 0.0
    total_llm_cost_usd: float = 0.0
    total_llm_tokens: int = 0
    cache_hit_rate: float = 0.0


class TrendPointSchema(BaseModel):
    """Single data point in a trend chart."""

    date: date  # ISO date
    reviews: int = 0
    issues: int = 0
    critical: int = 0
    avg_score: float = 0.0


class TrendStatsSchema(BaseModel):
    """Trend data over time."""

    period: str = "daily"  # daily, weekly, monthly
    start_date: date | None = None
    end_date: date | None = None
    points: list[TrendPointSchema] = Field(default_factory=list)


class CategoryBreakdownSchema(BaseModel):
    """Issues broken down by category."""

    category: str
    critical: int = 0
    warning: int = 0
    info: int = 0
    total: int = 0


__all__ = [
    "OverviewStatsSchema",
    "TrendPointSchema",
    "TrendStatsSchema",
    "CategoryBreakdownSchema",
]
