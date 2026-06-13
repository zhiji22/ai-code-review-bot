"""Review and ReviewComment models — code review records."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Review(Base, IdMixin, TimestampMixin):
    __tablename__ = "reviews"

    repository_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    pr_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(50), default="webhook", nullable=False)
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maintainability_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_reviewed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lines_of_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    info_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_tokens_prompt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_tokens_completion: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_tokens_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_comment_posted: Mapped[bool] = mapped_column(default=False, nullable=False)
    inline_comments_posted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    comments: Mapped[list["ReviewComment"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_reviews_repo_pr", "repository_id", "pr_number"),
        Index("ix_reviews_repo_pr_sha", "repository_id", "pr_number", "commit_sha"),
        Index("ix_reviews_status_created", "status", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_reviews_status",
        ),
        CheckConstraint(
            "overall_score >= 0 AND overall_score <= 100",
            name="ck_reviews_overall_score",
        ),
        CheckConstraint(
            "security_score >= 0 AND security_score <= 100",
            name="ck_reviews_security_score",
        ),
        CheckConstraint(
            "performance_score >= 0 AND performance_score <= 100",
            name="ck_reviews_performance_score",
        ),
        CheckConstraint(
            "maintainability_score >= 0 AND maintainability_score <= 100",
            name="ck_reviews_maintainability_score",
        ),
    )

    def __repr__(self) -> str:
        return f"<Review repo={self.repository_id} pr={self.pr_number} sha={self.commit_sha[:8]}>"


class ReviewComment(Base, IdMixin):
    __tablename__ = "review_comments"

    review_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    issue_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    matched_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=__import__("sqlalchemy").func.now(),
        nullable=False,
    )

    review: Mapped[Review] = relationship(back_populates="comments")

    __table_args__ = (
        Index("ix_review_comments_review_severity", "review_id", "severity"),
        Index("ix_review_comments_file", "review_id", "file_path"),
        CheckConstraint(
            "source IN ('ast', 'rule', 'llm')",
            name="ck_review_comments_source",
        ),
        CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_review_comments_severity",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_review_comments_confidence",
        ),
    )

    def __repr__(self) -> str:
        return f"<ReviewComment {self.source}:{self.severity} {self.file_path}:{self.line_number}>"
