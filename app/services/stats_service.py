"""
Stats service — aggregated metrics for dashboard.

 DESIGN.md §6 — /api/v1/stats/*
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func, case, and_, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import Review, ReviewComment
from app.models.repository import Repository
from app.models.llm_usage import LLMUsage
from app.schemas.stats import (
    OverviewStatsSchema,
    TrendStatsSchema,
    TrendPointSchema,
    CategoryBreakdownSchema,
)


class StatsService:
    """Dashboard statistics aggregation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ overview
    async def overview(
        self,
        *,
        repository_id: int | None = None,
        days: int = 30,
    ) -> OverviewStatsSchema:
        """High-level overview stats."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        base = select(Review).where(Review.created_at >= since)
        if repository_id:
            base = base.where(Review.repository_id == repository_id)

        # Total reviews
        total_reviews = int(
            await self.session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            or 0
        )

        # Average scores
        score_row = await self.session.execute(
            select(
                func.avg(Review.overall_score).label("avg_overall"),
                func.avg(Review.security_score).label("avg_security"),
                func.avg(Review.performance_score).label("avg_performance"),
                func.avg(Review.maintainability_score).label("avg_maintainability"),
            )
            .select_from(base.subquery())
        )
        scores = score_row.one_or_none()

        # Issue counts
        issue_row = await self.session.execute(
            select(
                func.sum(Review.critical_count).label("critical"),
                func.sum(Review.warning_count).label("warning"),
                func.sum(Review.info_count).label("info"),
            )
            .select_from(base.subquery())
        )
        issues = issue_row.one_or_none()

        # LLM usage
        llm_row = await self.session.execute(
            select(
                func.count().label("requests"),
                func.sum(LLMUsage.total_tokens).label("tokens"),
                func.sum(LLMUsage.cost_usd).label("cost"),
                func.sum(case((LLMUsage.cached.is_(True), 1), else_=0)).label(
                    "cached"
                ),
            )
            .join(Review, LLMUsage.review_id == Review.id)
            .where(Review.created_at >= since)
        )
        llm = llm_row.one_or_none()

        # Repositories
        total_repos = int(
            await self.session.scalar(
                select(func.count())
                .select_from(Repository)
                .where(Repository.is_active.is_(True))
            )
            or 0
        )

        llm_cached = int(llm.cached or 0)
        llm_requests = int(llm.requests or 0)

        critical = int(issues.critical or 0)
        warning = int(issues.warning or 0)
        info = int(issues.info or 0)

        return OverviewStatsSchema(
            total_reviews=total_reviews,
            total_repositories=total_repos,
            total_issues=critical + warning + info,
            critical_issues=critical,
            warning_issues=warning,
            info_issues=info,
            avg_overall_score=round(float(scores.avg_overall or 0), 1),
            avg_security_score=round(float(scores.avg_security or 0), 1),
            avg_performance_score=round(float(scores.avg_performance or 0), 1),
            avg_maintainability_score=round(
                float(scores.avg_maintainability or 0), 1
            ),
            total_llm_cost_usd=round(float(llm.cost or 0), 4),
            total_llm_tokens=int(llm.tokens or 0),
            cache_hit_rate=round(llm_cached / llm_requests, 4) if llm_requests else 0.0,
        )

    # ------------------------------------------------------------------ trends
    async def trends(
        self,
        *,
        repository_id: int | None = None,
        days: int = 30,
    ) -> TrendStatsSchema:
        """Daily trend data for charts."""
        start = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(
                func.date_trunc("day", Review.created_at).label("date"),
                func.count().label("reviews"),
                func.sum(Review.critical_count + Review.warning_count + Review.info_count).label(
                    "issues"
                ),
                func.sum(Review.critical_count).label("critical"),
                func.avg(Review.overall_score).label("avg_score"),
            )
            .where(Review.created_at >= start)
            .group_by("date")
            .order_by("date")
        )
        if repository_id:
            stmt = stmt.where(Review.repository_id == repository_id)

        result = await self.session.execute(stmt)
        points = []
        for row in result:
            points.append(
                TrendPointSchema(
                    date=row.date.date() if row.date else None,
                    reviews=int(row.reviews or 0),
                    issues=int(row.issues or 0),
                    critical=int(row.critical or 0),
                    avg_score=round(float(row.avg_score or 0), 1),
                )
            )

        return TrendStatsSchema(
            period=f"{days}d",
            start_date=start.date(),
            end_date=datetime.now(timezone.utc).date(),
            points=points,
        )

    # ------------------------------------------------------------------ breakdown
    async def category_breakdown(
        self,
        *,
        repository_id: int | None = None,
        days: int = 30,
    ) -> list[CategoryBreakdownSchema]:
        """Issue breakdown by category and severity."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(
                ReviewComment.category,
                ReviewComment.severity,
                func.count().label("count"),
            )
            .join(Review, ReviewComment.review_id == Review.id)
            .where(Review.created_at >= since)
            .group_by(ReviewComment.category, ReviewComment.severity)
        )
        if repository_id:
            stmt = stmt.where(Review.repository_id == repository_id)

        result = await self.session.execute(stmt)
        breakdown: dict[str, CategoryBreakdownSchema] = {}
        for row in result:
            cat = row.category or "other"
            if cat not in breakdown:
                breakdown[cat] = CategoryBreakdownSchema(
                    category=cat, critical=0, warning=0, info=0, total=0
                )
            entry = breakdown[cat]
            entry.total += int(row.count or 0)
            if row.severity == "critical":
                entry.critical += int(row.count or 0)
            elif row.severity == "warning":
                entry.warning += int(row.count or 0)
            else:
                entry.info += int(row.count or 0)

        return sorted(breakdown.values(), key=lambda x: x.total, reverse=True)
