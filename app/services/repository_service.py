"""
Repository service — CRUD operations for repositories.

 DESIGN.md §6 — /api/v1/repos/*
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.security import encrypt_secret
from app.models.repository import Repository
from app.schemas.repositories import (
    RepositoryCreateSchema,
    RepositorySettingsSchema,
    RepositoryUpdateSchema,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class RepositoryService:
    """CRUD + business logic for repositories."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ create
    async def create(self, data: RepositoryCreateSchema) -> Repository:
        """Register a new repository."""
        webhook_secret = data.webhook_secret or uuid4().hex
        encrypted = encrypt_secret(webhook_secret, settings.secret_key)

        repo = Repository(
            github_repo_id=data.github_repo_id,
            full_name=data.full_name,
            owner=data.owner,
            name=data.name,
            description=data.description,
            language=data.language,
            default_branch=data.default_branch or "main",
            is_private=data.is_private,
            webhook_secret=encrypted,
            installation_id=data.installation_id,
            settings=RepositorySettingsSchema().model_dump(),
        )
        self.session.add(repo)
        await self.session.commit()
        await self.session.refresh(repo)
        return repo

    # ------------------------------------------------------------------ read
    async def get_by_id(self, repo_id: int) -> Repository | None:
        """Get repository by primary key."""
        result = await self.session.execute(select(Repository).where(Repository.id == repo_id))
        return result.scalar_one_or_none()

    async def get_by_github_id(self, github_repo_id: int) -> Repository | None:
        """Get repository by GitHub's repo ID."""
        result = await self.session.execute(
            select(Repository).where(Repository.github_repo_id == github_repo_id)
        )
        return result.scalar_one_or_none()

    async def get_by_full_name(self, full_name: str) -> Repository | None:
        """Get repository by 'owner/name'."""
        result = await self.session.execute(
            select(Repository).where(Repository.full_name == full_name)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Repository], int]:
        """List active repositories with total count."""
        stmt = select(Repository).where(Repository.is_active.is_(True))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        result = await self.session.execute(
            stmt.order_by(Repository.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Repository], int]:
        """List all repositories (active and inactive) with total count."""
        stmt = select(Repository)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        result = await self.session.execute(
            stmt.order_by(Repository.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    # ------------------------------------------------------------------ update
    async def update(
        self,
        repo_id: int,
        data: RepositoryUpdateSchema,
    ) -> Repository | None:
        """Update repository fields."""
        values = data.model_dump(exclude_unset=True)
        if not values:
            return await self.get_by_id(repo_id)

        await self.session.execute(
            update(Repository).where(Repository.id == repo_id).values(**values)
        )
        await self.session.commit()
        return await self.get_by_id(repo_id)

    async def update_settings(
        self,
        repo_id: int,
        settings_data: RepositorySettingsSchema,
    ) -> Repository | None:
        """Update review settings JSONB."""
        repo = await self.get_by_id(repo_id)
        if not repo:
            return None
        repo.settings = settings_data.model_dump()
        await self.session.commit()
        await self.session.refresh(repo)
        return repo

    # ------------------------------------------------------------------ delete
    async def deactivate(self, repo_id: int) -> bool:
        """Soft-delete by setting is_active=False."""
        result = await self.session.execute(
            update(Repository).where(Repository.id == repo_id).values(is_active=False)
        )
        await self.session.commit()
        return result.rowcount > 0

    async def delete(self, repo_id: int) -> bool:
        """Hard-delete repository."""
        result = await self.session.execute(delete(Repository).where(Repository.id == repo_id))
        await self.session.commit()
        return result.rowcount > 0

    # ------------------------------------------------------------------ helpers
    async def touch_review(self, repo_id: int) -> None:
        """Update last_review_at and increment total_reviews."""
        await self.session.execute(
            update(Repository)
            .where(Repository.id == repo_id)
            .values(
                last_review_at=datetime.now(UTC),
                total_reviews=Repository.total_reviews + 1,
            )
        )
        await self.session.commit()

    async def get_webhook_secret(self, repo_id: int) -> str | None:
        """Decrypt and return webhook secret for HMAC verification."""
        repo = await self.get_by_id(repo_id)
        if not repo or not repo.webhook_secret:
            return None
        from app.core.security import decrypt_secret

        return decrypt_secret(repo.webhook_secret, settings.secret_key)
