"""Code embedding model — pgvector storage for semantic code search."""

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # pgvector optional at runtime; migration installs it


EMBEDDING_DIM = 1536


class CodeEmbedding(Base, IdMixin, TimestampMixin):
    __tablename__ = "code_embeddings"

    repository_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding = (
        mapped_column(Vector(EMBEDDING_DIM), nullable=True)
        if Vector
        else mapped_column(Text, nullable=True)
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<CodeEmbedding {self.file_path}:{self.start_line}-{self.end_line}>"
