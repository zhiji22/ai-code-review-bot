"""Server-Sent Events (SSE) endpoint for real-time review status updates.

Clients subscribe to /api/v1/reviews/{id}/stream to receive live updates
as the review pipeline progresses through its stages.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.models.review import Review

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["reviews-sse"])


async def _review_status_event(review_id: int, db_session: AsyncSession) -> dict[str, Any] | None:
    """Fetch current review status from DB."""
    result = await db_session.execute(
        select(
            Review.id,
            Review.status,
            Review.overall_score,
            Review.files_reviewed,
            Review.files_total,
            Review.critical_count,
            Review.warning_count,
            Review.info_count,
            Review.error_message,
            Review.reviewed_at,
        ).where(Review.id == review_id)
    )
    row = result.first()
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "overall_score": row.overall_score,
        "files_reviewed": row.files_reviewed,
        "files_total": row.files_total,
        "critical_count": row.critical_count,
        "warning_count": row.warning_count,
        "info_count": row.info_count,
        "error_message": row.error_message,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


async def _subscribe_review_stream(review_id: int, request: Request) -> AsyncIterator[bytes]:
    """Generate SSE events for a review until terminal state or disconnect.

    Polls DB every 1.5s for status changes. Uses Redis pubsub as optional
    fast-path when review tasks publish updates.
    """
    from app.core.database import get_session_factory

    poll_interval = 1.5  # seconds
    terminal_states: set[str] = {"completed", "failed", "cancelled"}
    last_state: dict[str, Any] | None = None

    # Send initial hello
    yield _sse_event("connected", {"review_id": review_id})

    session_factory = get_session_factory()
    async with session_factory() as db_session:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.debug("SSE client disconnected for review %s", review_id)
                break

            current = await _review_status_event(review_id, db_session)
            if current is None:
                yield _sse_event("error", {"message": "Review not found"})
                break

            # Emit only on change
            if current != last_state:
                yield _sse_event("status", current)
                last_state = current

            if current["status"] in terminal_states:
                yield _sse_event("done", {"status": current["status"]})
                break

            await asyncio.sleep(poll_interval)


def _sse_event(event: str, data: dict[str, Any]) -> bytes:
    """Format a single SSE event frame."""
    payload = json.dumps(
        {"event": event, "data": data, "ts": datetime.now(UTC).isoformat()},
        default=str,
    )
    return f"event: {event}\ndata: {payload}\n\n".encode()


@router.get(
    "/{review_id}/stream",
    summary="Stream review status updates (SSE)",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}},
        404: {"description": "Review not found"},
    },
)
async def stream_review_status(
    review_id: int,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    """Server-Sent Events stream for real-time review status updates.

    Events:
    - `connected`: subscription confirmed
    - `status`: review state changed (queued/processing/completed/failed)
    - `done`: terminal state reached, stream ends
    - `error`: review missing or stream error
    """
    return StreamingResponse(
        _subscribe_review_stream(review_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )
