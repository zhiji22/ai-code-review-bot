"""
Webhook receiver endpoint.

Per DESIGN.md §3: Webhook Handler with HMAC verification + idempotency + queue.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, Header, Request, status
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.idempotency import (
    build_webhook_idempotency_key,
    check_idempotency,
)
from app.core.security import verify_webhook

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    request: Request,
    x_github_event: str = Header(..., alias="X-GitHub-Event"),
    x_github_delivery: str = Header(..., alias="X-GitHub-Delivery"),
    x_hub_signature_256: str = Header(..., alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """Receive and validate GitHub webhook.

    Flow:
    1. Verify HMAC-SHA256 signature
    2. Parse event type
    3. For pull_request events: check idempotency → queue review task
    4. For ping events: return ack

    Returns:
        202 Accepted with task ID.
    """
    settings = get_settings()

    # Step 1: Verify signature
    body = await verify_webhook(request, settings.github_webhook_secret)

    # Step 2: Handle ping
    if x_github_event == "ping":
        logger.info("webhook_ping_received", delivery_id=x_github_delivery)
        return {"status": "pong", "event": "ping"}

    # Step 3: Handle pull_request events
    if x_github_event != "pull_request":
        logger.info(
            "webhook_ignored_event",
            github_event=x_github_event,
            delivery_id=x_github_delivery,
        )
        return {"status": "ignored", "event": x_github_event}

    # Parse payload
    try:
        payload = json.loads(body)
        from app.schemas.webhook import WebhookPREvent

        event = WebhookPREvent.model_validate(payload)
    except ValidationError as e:
        logger.error("webhook_payload_invalid", error=str(e))
        return {"status": "error", "detail": "Invalid payload"}

    # Check idempotency (§7.4)
    idem_key = build_webhook_idempotency_key(
        repo_full_name=event.repository.full_name,
        pr_number=event.number,
        commit_sha=event.pull_request.head.sha,
    )

    try:
        await check_idempotency(idem_key, ttl=settings.idempotency_ttl)
    except Exception:
        raise

    # Queue review task
    from app.tasks.review_tasks import queue_pr_review

    task = queue_pr_review.delay(
        repo_full_name=event.repository.full_name,
        pr_number=event.number,
        commit_sha=event.pull_request.head.sha,
        installation_id=_extract_installation_id(payload),
    )

    logger.info(
        "webhook_queued",
        repo=event.repository.full_name,
        pr_number=event.number,
        commit=event.pull_request.head.sha,
        task_id=task.id,
    )

    return {
        "status": "accepted",
        "event": "pull_request",
        "task_id": task.id,
    }


def _extract_installation_id(payload: dict[str, Any]) -> int | None:
    """Extract installation ID from webhook payload."""
    installation: dict[str, Any] = payload.get("installation", {})
    return installation.get("id")
