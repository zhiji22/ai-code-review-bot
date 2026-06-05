"""Repository settings endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import ApiResponse, PaginatedResponse
from app.schemas.repositories import (
    RepositoryListSchema,
    RepositorySchema,
    RepositorySettingsSchema,
    RepositoryUpdateSchema,
)
from app.services.repository_service import RepositoryService

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get(
    "",
    response_model=ApiResponse[PaginatedResponse[RepositoryListSchema]],
    summary="List repositories",
)
async def list_repositories(
    db: Annotated[AsyncSession, Depends(get_db)],
    active_only: bool = Query(True, description="Only active repositories"),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedResponse[RepositoryListSchema]]:
    service = RepositoryService(db)
    repos, total = await service.list_active(limit=limit) if active_only else (await service._list_all(limit=limit), 0)
    # Convert to list schema
    items = [
        RepositoryListSchema(
            id=r.id,
            full_name=r.full_name,
            owner=r.owner,
            name=r.name,
            is_private=r.is_private,
            is_active=r.is_active,
            language=r.language,
            total_reviews=r.total_reviews,
            last_review_at=r.last_review_at,
        )
        for r in repos
    ]
    return ApiResponse(
        data=PaginatedResponse(
            items=items,
            total=total,
            limit=limit,
            cursor=cursor,
        )
    )


@router.get(
    "/{repo_id}",
    response_model=ApiResponse[RepositorySchema],
    summary="Get repository detail",
)
async def get_repository(
    repo_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RepositorySchema]:
    service = RepositoryService(db)
    repo = await service.get_by_id(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    return ApiResponse(data=RepositorySchema.model_validate(repo, from_attributes=True))


@router.patch(
    "/{repo_id}",
    response_model=ApiResponse[RepositorySchema],
    summary="Update repository settings",
)
async def update_repository(
    repo_id: int,
    payload: RepositoryUpdateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RepositorySchema]:
    service = RepositoryService(db)
    repo = await service.update(repo_id, payload)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    return ApiResponse(data=RepositorySchema.model_validate(repo, from_attributes=True))


@router.put(
    "/{repo_id}/settings",
    response_model=ApiResponse[RepositorySchema],
    summary="Update repository review settings",
)
async def update_settings(
    repo_id: int,
    payload: RepositorySettingsSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[RepositorySchema]:
    service = RepositoryService(db)
    repo = await service.update_settings(repo_id, payload)
    if repo is None:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    return ApiResponse(data=RepositorySchema.model_validate(repo, from_attributes=True))


@router.delete(
    "/{repo_id}",
    status_code=status.HTTP_200_OK,
    summary="Deactivate repository",
)
async def deactivate_repository(
    repo_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    service = RepositoryService(db)
    success = await service.deactivate(repo_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    return {"status": "deactivated"}
