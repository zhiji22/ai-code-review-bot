"""Rule management endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import ApiResponse, PaginatedResponse
from app.schemas.rules import (
    RuleCreateSchema,
    RuleListSchema,
    RuleSchema,
    RuleUpdateSchema,
)
from app.services.rule_service import RuleService

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get(
    "",
    response_model=ApiResponse[PaginatedResponse[RuleListSchema]],
    summary="List rules",
)
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(None, description="Filter by category"),
    severity: str | None = Query(None, description="Filter by severity"),
    enabled: bool | None = Query(None, description="Filter by enabled state"),
    builtin: bool | None = Query(None, description="Filter builtin/custom"),
    repository_id: int | None = Query(None, description="Filter by repository"),
    limit: int = Query(50, ge=1, le=200),
) -> ApiResponse[PaginatedResponse[RuleListSchema]]:
    service = RuleService(db)
    rules, total = await service.list_rules(
        category=category,
        severity=severity,
        enabled=enabled,
        is_builtin=builtin,
        repository_id=repository_id,
        limit=limit,
    )
    items = [
        RuleListSchema(
            id=r.id,
            rule_id=r.rule_id,
            name=r.name,
            category=r.category,
            severity=r.severity,
            enabled=r.enabled,
            is_builtin=r.is_builtin,
            languages=r.languages or [],
        )
        for r in rules
    ]
    return ApiResponse(
        data=PaginatedResponse(
            items=items,
            total=total,
            limit=limit,
        )
    )


@router.get(
    "/{rule_id}",
    response_model=ApiResponse[RuleSchema],
    summary="Get rule detail",
)
async def get_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RuleSchema]:
    service = RuleService(db)
    rule = await service.get_by_id(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return ApiResponse(data=RuleSchema.model_validate(rule, from_attributes=True))


@router.post(
    "",
    response_model=ApiResponse[RuleSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Create custom rule",
)
async def create_rule(
    payload: RuleCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RuleSchema]:
    service = RuleService(db)
    rule = await service.create(payload)
    return ApiResponse(data=RuleSchema.model_validate(rule, from_attributes=True))


@router.patch(
    "/{rule_id}",
    response_model=ApiResponse[RuleSchema],
    summary="Update rule",
)
async def update_rule(
    rule_id: int,
    payload: RuleUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RuleSchema]:
    service = RuleService(db)
    rule = await service.update(rule_id, payload)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return ApiResponse(data=RuleSchema.model_validate(rule, from_attributes=True))


@router.post(
    "/{rule_id}/toggle",
    response_model=ApiResponse[RuleSchema],
    summary="Enable/disable rule",
)
async def toggle_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RuleSchema]:
    service = RuleService(db)
    rule = await service.toggle(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return ApiResponse(data=RuleSchema.model_validate(rule, from_attributes=True))


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete custom rule",
)
async def delete_rule(
    rule_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    service = RuleService(db)
    success = await service.delete(rule_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule {rule_id} not found or cannot delete builtin rule",
        )
    return {"status": "deleted"}
