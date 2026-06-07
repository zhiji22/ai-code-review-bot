"""
Review service — CRUD + business logic for reviews and comments.

 DESIGN.md §6 — /api/v1/reviews/*
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.review import Review, ReviewComment
from app.models.repository import Repository
from app.schemas.reviews import (
    ReviewCreateSchema,
    ReviewFiltersSchema,
    ReviewSchema,
    ReviewListSchema,
)


class ReviewService:
    """CRUD + orchestration for code reviews."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ create
    async def create_from_pipeline(
        self,
        *,
        repository_id: int,
        pr_number: int,
        commit_sha: str,
        pr_title: str,
        pr_author: str,
        trigger: str = "webhook",
        files_reviewed: int = 0,
        files_total: int = 0,
        lines_of_code: int = 0,
        additions: int = 0,
        deletions: int = 0,
        overall_score: int = 0,
        security_score: int = 0,
        performance_score: int = 0,
        maintainability_score: int = 0,
        critical_count: int = 0,
        warning_count: int = 0,
        info_count: int = 0,
        llm_model: str | None = None,
        llm_tokens_prompt: int = 0,
        llm_tokens_completion: int = 0,
        llm_tokens_total: int = 0,
        llm_cost_usd: float = 0.0,
        duration_ms: int = 0,
        summary: str = "",
        raw_result: dict[str, Any] | None = None,
        pr_comment_posted: bool = False,
        inline_comments_posted: int = 0,
    ) -> Review:
        """Persist a completed review from the pipeline."""
        review = Review(
            repository_id=repository_id,
            pr_number=pr_number,
            commit_sha=commit_sha,
            pr_title=pr_title,
            pr_author=pr_author,
            status="completed",
            trigger=trigger,
            files_reviewed=files_reviewed,
            files_total=files_total,
            lines_of_code=lines_of_code,
            additions=additions,
            deletions=deletions,
            overall_score=overall_score,
            security_score=security_score,
            performance_score=performance_score,
            maintainability_score=maintainability_score,
            critical_count=critical_count,
            warning_count=warning_count,
            info_count=info_count,
            llm_model=llm_model,
            llm_tokens_prompt=llm_tokens_prompt,
            llm_tokens_completion=llm_tokens_completion,
            llm_tokens_total=llm_tokens_total,
            llm_cost_usd=llm_cost_usd,
            duration_ms=duration_ms,
            summary=summary,
            raw_result=raw_result or {},
            pr_comment_posted=pr_comment_posted,
            inline_comments_posted=inline_comments_posted,
            reviewed_at=datetime.now(timezone.utc),
        )
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def create_pending(
        self,
        *,
        repository_id: int,
        pr_number: int,
        commit_sha: str,
        pr_title: str,
        pr_author: str,
        trigger: str = "webhook",
    ) -> Review:
        """Create a pending review entry (before pipeline runs)."""
        review = Review(
            repository_id=repository_id,
            pr_number=pr_number,
            commit_sha=commit_sha,
            pr_title=pr_title,
            pr_author=pr_author,
            status="pending",
            trigger=trigger,
        )
        self.session.add(review)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def mark_failed(
        self,
        review_id: int,
        error_message: str,
    ) -> None:
        """Mark a review as failed."""
        await self.session.execute(
            update(Review)
            .where(Review.id == review_id)
            .values(
                status="failed",
                error_message=error_message,
                reviewed_at=datetime.now(timezone.utc),
            )
        )
        await self.session.commit()

    async def save_comments(
        self,
        review_id: int,
        comments: list[dict[str, Any]],
    ) -> list[ReviewComment]:
        """Bulk-insert review comments."""
        objs = []
        for c in comments:
            objs.append(
                ReviewComment(
                    review_id=review_id,
                    file_path=c["file_path"],
                    line_number=c.get("line_number", 1),
                    line_end=c.get("line_end"),
                    source=c.get("source", "rule"),
                    category=c.get("category", "general"),
                    severity=c.get("severity", "info"),
                    message=c["message"],
                    suggestion=c.get("suggestion"),
                    rule_id=c.get("rule_id"),
                    confidence=c.get("confidence", 1.0),
                    issue_type=c.get("issue_type"),
                    matched_text=c.get("matched_text"),
                    extra=c.get("extra"),
                )
            )
        self.session.add_all(objs)
        await self.session.commit()
        return objs

    # ------------------------------------------------------------------ read
    async def get_by_id(self, review_id: int) -> Review | None:
        """Get review by ID with comments loaded."""
        result = await self.session.execute(
            select(Review)
            .options(selectinload(Review.comments))
            .where(Review.id == review_id)
        )
        return result.scalar_one_or_none()

    async def list_reviews(
        self,
        filters: ReviewFiltersSchema,
    ) -> tuple[list[Review], int]:
        """List reviews with filtering, sorting, and pagination."""
        stmt = select(Review)

        conditions = []
        if filters.repository_id:
            conditions.append(Review.repository_id == filters.repository_id)
        if filters.status:
            conditions.append(Review.status == filters.status)
        if filters.pr_number:
            conditions.append(Review.pr_number == filters.pr_number)
        if filters.min_score is not None:
            conditions.append(Review.overall_score >= filters.min_score)
        if filters.max_score is not None:
            conditions.append(Review.overall_score <= filters.max_score)
        if filters.date_from:
            conditions.append(Review.created_at >= filters.date_from)
        if filters.date_to:
            conditions.append(Review.created_at <= filters.date_to)

        if conditions:
            stmt = stmt.where(and_(*conditions))

        total = await self.session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )

        sort_col = getattr(Review, filters.sort_by, Review.created_at)
        if filters.sort_order == "asc":
            stmt = stmt.order_by(sort_col.asc())
        else:
            stmt = stmt.order_by(sort_col.desc())

        if filters.cursor:
            stmt = stmt.where(Review.id < filters.cursor)

        result = await self.session.execute(
            stmt.offset(filters.offset).limit(filters.limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_latest_for_pr(
        self,
        repository_id: int,
        pr_number: int,
    ) -> Review | None:
        """Get most recent review for a PR."""
        result = await self.session.execute(
            select(Review)
            .where(
                and_(
                    Review.repository_id == repository_id,
                    Review.pr_number == pr_number,
                )
            )
            .order_by(desc(Review.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_comments(self, review_id: int) -> list[ReviewComment]:
        """Get all comments for a review."""
        result = await self.session.execute(
            select(ReviewComment)
            .where(ReviewComment.review_id == review_id)
            .order_by(
                ReviewComment.file_path,
                ReviewComment.line_number,
            )
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------ stats
    async def count_by_repo(
        self,
        repository_id: int,
        *,
        since: datetime | None = None,
    ) -> int:
        """Count reviews for a repository (optionally since timestamp)."""
        stmt = select(func.count()).where(Review.repository_id == repository_id)
        if since:
            stmt = stmt.where(Review.created_at >= since)
        return int(await self.session.scalar(stmt) or 0)
