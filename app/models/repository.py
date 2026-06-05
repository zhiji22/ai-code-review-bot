"""Repository model — tracked GitHub repositories."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Repository(Base, IdMixin, TimestampMixin):
    __tablename__ = "repositories"

    github_repo_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(
        String(500), unique=True, nullable=False, index=True
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(255), default="main", nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    webhook_secret: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    settings: Mapped[dict] = mapped_column(
        JSONB,
        default={
            "auto_review": True,
            "comment_style": "detailed",
            "severity_threshold": "warning",
            "max_files_per_review": 100,
            "enable_llm": True,
            "enable_ast": True,
            "enable_rules": True,
        },
        nullable=False,
    )
    last_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<Repository {self.full_name}>"
