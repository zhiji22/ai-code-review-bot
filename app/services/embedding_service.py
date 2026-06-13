"""Embedding service for code semantic search via pgvector.

Provides code chunking, OpenAI embedding generation, and similarity search
over the code_embeddings table.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from app.core.config import settings
from app.models.code_embedding import CodeEmbedding

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Chunking parameters
CHUNK_SIZE_LINES = 50
CHUNK_OVERLAP_LINES = 5
MAX_CHUNK_CHARS = 8000  # OpenAI token limit safety
EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dims, cheap
EMBEDDING_DIM = 1536


@dataclass
class CodeChunk:
    """A chunk of code for embedding."""

    file_path: str
    language: str
    start_line: int
    end_line: int
    chunk_text: str
    chunk_hash: str

    @classmethod
    def from_text(
        cls,
        file_path: str,
        language: str,
        lines: list[str],
        start_idx: int,
        end_idx: int,
    ) -> CodeChunk:
        chunk_lines = lines[start_idx:end_idx]
        chunk_text = "\n".join(chunk_lines)
        chunk_hash = hashlib.sha256(
            f"{file_path}:{start_idx}:{end_idx}:{chunk_text}".encode()
        ).hexdigest()
        return cls(
            file_path=file_path,
            language=language,
            start_line=start_idx + 1,
            end_line=end_idx,
            chunk_text=chunk_text[:MAX_CHUNK_CHARS],
            chunk_hash=chunk_hash,
        )


def chunk_code(file_path: str, code: str, language: str = "unknown") -> list[CodeChunk]:
    """Split code into overlapping line-based chunks.

    Args:
        file_path: File path for metadata.
        code: Full source code text.
        language: Programming language.

    Returns:
        List of CodeChunk objects.
    """
    lines = code.splitlines()
    if not lines:
        return []

    chunks: list[CodeChunk] = []
    step = CHUNK_SIZE_LINES - CHUNK_OVERLAP_LINES
    for i in range(0, len(lines), step):
        end = min(i + CHUNK_SIZE_LINES, len(lines))
        chunks.append(CodeChunk.from_text(file_path, language, lines, i, end))
        if end >= len(lines):
            break
    return chunks


@dataclass
class EmbeddingResult:
    """Result of embedding generation for a file."""

    file_path: str
    chunks: list[CodeChunk] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)
    model: str = EMBEDDING_MODEL
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None and len(self.embeddings) == len(self.chunks)


class EmbeddingService:
    """Service for generating and storing code embeddings with pgvector."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
            )
        return self._client

    async def embed_file(
        self,
        repository_id: int,
        file_path: str,
        code: str,
        language: str = "unknown",
    ) -> EmbeddingResult:
        """Chunk a file, embed chunks, and store in pgvector.

        Args:
            repository_id: Repository DB ID.
            file_path: File path in repo.
            code: Full source code.
            language: Language identifier.

        Returns:
            EmbeddingResult with chunks/embeddings.
        """
        result = EmbeddingResult(file_path=file_path)
        chunks = chunk_code(file_path, code, language)
        if not chunks:
            result.error = "empty_file"
            return result

        result.chunks = chunks

        try:
            resp = await self.client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=[c.chunk_text for c in chunks],
            )
            result.embeddings = [d.embedding for d in resp.data]
        except Exception as exc:
            logger.exception("Embedding generation failed for %s", file_path)
            result.error = str(exc)
            return result

        await self._store_embeddings(repository_id, result)
        return result

    async def _store_embeddings(self, repository_id: int, result: EmbeddingResult) -> None:
        """Replace existing embeddings for the file with new ones."""
        # Delete existing chunks for this file in this repo
        await self.session.execute(
            text("DELETE FROM code_embeddings WHERE repository_id = :rid AND file_path = :fp"),
            {"rid": repository_id, "fp": result.file_path},
        )
        for chunk, vec in zip(result.chunks, result.embeddings, strict=True):
            embedding = CodeEmbedding(
                repository_id=repository_id,
                file_path=chunk.file_path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                chunk_text=chunk.chunk_text,
                language=chunk.language,
                chunk_hash=chunk.chunk_hash,
                embedding=vec,
                metadata_={
                    "model": EMBEDDING_MODEL,
                    "dim": EMBEDDING_DIM,
                },
            )
            self.session.add(embedding)
        await self.session.flush()

    async def search_similar(
        self,
        repository_id: int,
        query: str,
        top_k: int = 5,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over code embeddings.

        Args:
            repository_id: Repository to search.
            query: Natural language or code query.
            top_k: Max results.
            language: Optional language filter.

        Returns:
            List of {file_path, start_line, end_line, chunk_text, language,
            similarity} dicts sorted by similarity desc.
        """
        try:
            resp = await self.client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=[query],
            )
            query_vec = resp.data[0].embedding
        except Exception as exc:
            logger.exception("Query embedding failed")
            raise RuntimeError(f"Failed to embed query: {exc}") from exc

        # Cosine similarity search via pgvector
        sql = text(
            """
            SELECT
                file_path,
                start_line,
                end_line,
                chunk_text,
                language,
                1 - (embedding <=> :qvec::vector) AS similarity
            FROM code_embeddings
            WHERE repository_id = :rid
            ORDER BY embedding <=> :qvec::vector
            LIMIT :k
            """
        )
        params: dict[str, Any] = {
            "rid": repository_id,
            "qvec": str(query_vec),
            "k": top_k,
        }
        rows = (await self.session.execute(sql, params)).mappings().all()

        results = []
        for row in rows:
            entry = dict(row)
            if language and entry.get("language") != language:
                continue
            results.append(entry)
        return results

    async def delete_for_file(self, repository_id: int, file_path: str) -> int:
        """Delete all embeddings for a file. Returns count deleted."""
        result = await self.session.execute(
            text(
                "DELETE FROM code_embeddings "
                "WHERE repository_id = :rid AND file_path = :fp "
                "RETURNING id"
            ),
            {"rid": repository_id, "fp": file_path},
        )
        count = len(result.fetchall())
        await self.session.flush()
        return count

    async def delete_for_repository(self, repository_id: int) -> int:
        """Delete all embeddings for a repository."""
        result = await self.session.execute(
            text("DELETE FROM code_embeddings WHERE repository_id = :rid RETURNING id"),
            {"rid": repository_id},
        )
        count = len(result.fetchall())
        await self.session.flush()
        return count
