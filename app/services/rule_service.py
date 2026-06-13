"""
Rule service — CRUD for custom and builtin rules.

 DESIGN.md §6 — /api/v1/rules/*
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, select, update

from app.models.rule import Rule

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.schemas.rules import RuleCreateSchema, RuleUpdateSchema


class RuleService:
    """CRUD for review rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ create
    async def create(self, data: RuleCreateSchema) -> Rule:
        """Create a custom rule."""
        rule = Rule(
            rule_id=data.rule_id,
            name=data.name,
            description=data.description,
            category=data.category,
            severity=data.severity,
            pattern=data.pattern,
            message=data.message,
            suggestion=data.suggestion,
            languages=data.languages or ["python"],
            enabled=data.enabled if data.enabled is not None else True,
            is_builtin=False,
            repository_id=data.repository_id,
        )
        self.session.add(rule)
        await self.session.commit()
        await self.session.refresh(rule)
        return rule

    # ------------------------------------------------------------------ read
    async def get_by_id(self, rule_id: int) -> Rule | None:
        result = await self.session.execute(select(Rule).where(Rule.id == rule_id))
        return result.scalar_one_or_none()

    async def get_by_rule_id(self, rule_id: str) -> Rule | None:
        """Get rule by string rule_id (e.g. 'SEC001')."""
        result = await self.session.execute(select(Rule).where(Rule.rule_id == rule_id))
        return result.scalar_one_or_none()

    async def list_rules(
        self,
        *,
        repository_id: int | None = None,
        category: str | None = None,
        severity: str | None = None,
        enabled: bool | None = None,
        is_builtin: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Rule], int]:
        """List rules with optional filters."""
        stmt = select(Rule)
        conditions: list[Any] = []
        if repository_id is not None:
            # Include both repo-specific and global/builtin rules
            conditions.append(
                (Rule.repository_id == repository_id) | (Rule.repository_id.is_(None))
            )
        if category:
            conditions.append(Rule.category == category)
        if severity:
            conditions.append(Rule.severity == severity)
        if enabled is not None:
            conditions.append(Rule.enabled.is_(enabled))
        if is_builtin is not None:
            conditions.append(Rule.is_builtin.is_(is_builtin))

        if conditions:
            stmt = stmt.where(and_(*conditions))

        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        result = await self.session.execute(
            stmt.order_by(Rule.category, Rule.rule_id).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_for_repository(
        self,
        repository_id: int,
        *,
        enabled_only: bool = True,
    ) -> list[Rule]:
        """Get all rules applicable to a repository (builtin + repo-specific)."""
        stmt = select(Rule).where(
            (Rule.repository_id == repository_id) | (Rule.repository_id.is_(None))
        )
        if enabled_only:
            stmt = stmt.where(Rule.enabled.is_(True))
        result = await self.session.execute(stmt.order_by(Rule.category))
        return list(result.scalars().all())

    # ------------------------------------------------------------------ update
    async def update(
        self,
        rule_id: int,
        data: RuleUpdateSchema,
    ) -> Rule | None:
        values = data.model_dump(exclude_unset=True)
        if not values:
            return await self.get_by_id(rule_id)
        await self.session.execute(update(Rule).where(Rule.id == rule_id).values(**values))
        await self.session.commit()
        return await self.get_by_id(rule_id)

    async def toggle(self, rule_id: int, enabled: bool) -> Rule | None:
        """Enable/disable a rule."""
        await self.session.execute(update(Rule).where(Rule.id == rule_id).values(enabled=enabled))
        await self.session.commit()
        return await self.get_by_id(rule_id)

    # ------------------------------------------------------------------ delete
    async def delete(self, rule_id: int) -> bool:
        """Delete a custom rule (cannot delete builtins)."""
        rule = await self.get_by_id(rule_id)
        if not rule or rule.is_builtin:
            return False
        await self.session.execute(delete(Rule).where(Rule.id == rule_id))
        await self.session.commit()
        return True
