"""Statistics endpoints — overview, trends, breakdowns."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import ApiResponse
from app.schemas.stats import (
    CategoryBreakdownSchema,
    OverviewStatsSchema,
    TrendStatsSchema,
)
from app.services.stats_service import StatsService

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "/overview",
    response_model=ApiResponse[OverviewStatsSchema],
    summary="Dashboard overview statistics",
)
async def get_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    repository_id: int | None = Query(None, description="Filter by repository"),
) -> ApiResponse[OverviewStatsSchema]:
    service = StatsService(db)
    stats = await service.overview(repository_id=repository_id)
    return ApiResponse(data=stats)


@router.get(
    "/trends",
    response_model=ApiResponse[TrendStatsSchema],
    summary="Review trends over time",
)
async def get_trends(
    db: Annotated[AsyncSession, Depends(get_db)],
    repository_id: int | None = Query(None),
    days: int = Query(30, ge=1, le=365, description="Number of days"),
) -> ApiResponse[TrendStatsSchema]:
    service = StatsService(db)
    stats = await service.trends(repository_id=repository_id, days=days)
    return ApiResponse(data=stats)


@router.get(
    "/breakdown",
    response_model=ApiResponse[list[CategoryBreakdownSchema]],
    summary="Issue breakdown by category and severity",
)
async def get_breakdown(
    db: Annotated[AsyncSession, Depends(get_db)],
    repository_id: int | None = Query(None),
    days: int = Query(30, ge=1, le=365),
) -> ApiResponse[list[CategoryBreakdownSchema]]:
    service = StatsService(db)
    breakdown = await service.category_breakdown(
        repository_id=repository_id,
        days=days,
    )
    return ApiResponse(data=breakdown)
