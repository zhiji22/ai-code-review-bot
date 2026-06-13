"""Review endpoints — list, detail, trigger, comments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import ApiResponse, PaginatedResponse
from app.schemas.reviews import (
    ReviewCommentSchema,
    ReviewCreateSchema,
    ReviewFiltersSchema,
    ReviewListSchema,
    ReviewSchema,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get(
    "",
    response_model=ApiResponse[PaginatedResponse[ReviewListSchema]],
    summary="List reviews",
)
async def list_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    repository_id: int | None = Query(None, description="Filter by repository"),
    pr_number: int | None = Query(None, description="Filter by PR number"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    author: str | None = Query(None, description="Filter by PR author"),
    min_score: float | None = Query(None, ge=0, le=100, description="Minimum overall score"),
    max_score: float | None = Query(None, ge=0, le=100, description="Maximum overall score"),
    sort: str = Query("created_at", description="Sort field"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    cursor: str | None = Query(None, description="Pagination cursor"),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedResponse[ReviewListSchema]]:
    filters = ReviewFiltersSchema(
        repository_id=repository_id,
        pr_number=pr_number,
        status=status_filter,
        author=author,
        min_score=min_score,
        max_score=max_score,
        sort_by=sort,
        sort_order=order,
        cursor=cursor,
        limit=limit,
    )
    service = ReviewService(db)
    items, total = await service.list_reviews(filters)
    return ApiResponse(
        data=PaginatedResponse(
            items=items,
            total=total,
            limit=limit,
            cursor=cursor,
            next_cursor=None,
        )
    )


@router.get(
    "/{review_id}",
    response_model=ApiResponse[ReviewSchema],
    summary="Get review detail",
)
async def get_review(
    review_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ReviewSchema]:
    service = ReviewService(db)
    review = await service.get_by_id(review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )
    return ApiResponse(data=review)


@router.get(
    "/{review_id}/comments",
    response_model=ApiResponse[list[ReviewCommentSchema]],
    summary="Get review comments",
)
async def get_review_comments(
    review_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[list[ReviewCommentSchema]]:
    service = ReviewService(db)
    review = await service.get_by_id(review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )
    comments = await service.get_comments(review_id)
    return ApiResponse(data=comments)


@router.post(
    "",
    response_model=ApiResponse[ReviewSchema],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger manual review",
)
async def trigger_review(
    payload: ReviewCreateSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ReviewSchema]:
    """Queue a manual review for a PR (async, returns pending review)."""
    service = ReviewService(db)
    review = await service.create_pending(
        repository_id=payload.repository_id,
        pr_number=payload.pr_number,
        commit_sha=payload.commit_sha or "",
        pr_title=payload.pr_title or "",
        pr_author=payload.pr_author or "",
    )
    # TODO: queue Celery task for actual review
    from app.tasks.review_tasks import queue_pr_review

    queue_pr_review.delay(
        repo_full_name=payload.repository_full_name,
        pr_number=payload.pr_number,
        commit_sha=payload.commit_sha or "",
    )
    return ApiResponse(data=review)
