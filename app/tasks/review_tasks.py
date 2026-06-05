"""
Celery review tasks — async PR review pipeline.

Per DESIGN.md §3: Review Engine runs as Celery task with retry/timeout/backoff.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


class ReviewTask(Task):
    """Base task class with custom error handling."""

    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True  # Exponential backoff
    retry_backoff_max = 300  # 5 minutes
    retry_jitter = True


@celery_app.task(
    base=ReviewTask,
    name="app.tasks.review_tasks.queue_pr_review",
    bind=True,
)
def queue_pr_review(
    self,
    repo_full_name: str,
    pr_number: int,
    commit_sha: str,
    installation_id: int | None = None,
) -> Any:
    """Queue a PR for full review pipeline.

    This is the main entry point triggered by webhook handler.

    Args:
        repo_full_name: e.g. "owner/repo".
        pr_number: Pull request number.
        commit_sha: Head commit SHA.
        installation_id: GitHub App installation ID.
    """
    logger.info(
        "review_task_started",
        repo=repo_full_name,
        pr_number=pr_number,
        commit=commit_sha,
        task_id=self.request.id,
    )

    # Run the async pipeline in a sync Celery context
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            _execute_review_pipeline(
                repo_full_name=repo_full_name,
                pr_number=pr_number,
                commit_sha=commit_sha,
                installation_id=installation_id,
            )
        )
        return result
    finally:
        loop.close()


async def _execute_review_pipeline(
    repo_full_name: str,
    pr_number: int,
    commit_sha: str,
    installation_id: int | None,
) -> dict[str, Any]:
    """Execute the full review pipeline (async).

    Pipeline (per DESIGN.md §3 Review Engine):
    1. Fetch PR diff and files from GitHub API
    2. Filter files (size, type)
    3. Run parallel analysis: AST → Rule Engine → LLM
    4. Aggregate results
    5. Calculate score
    6. Post comment to PR

    Returns:
        Review summary dict.
    """
    from app.services.review_service import ReviewService

    service = ReviewService(
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        commit_sha=commit_sha,
        installation_id=installation_id,
    )

    result = await service.run_review()

    logger.info(
        "review_pipeline_completed",
        repo=repo_full_name,
        pr_number=pr_number,
        score=result.score,
        issues_count=len(result.issues),
    )

    return result.to_dict()


@celery_app.task(name="app.tasks.review_tasks.cleanup_expired_keys")
def cleanup_expired_keys() -> dict[str, int]:
    """Clean up expired idempotency/rate-limit keys (called by beat)."""
    logger.info("cleanup_task_running")
    # Redis handles TTL automatically; this is a no-op placeholder
    return {"status": "ok", "cleaned": 0}


@celery_app.task(name="app.tasks.review_tasks.reset_daily_budget")
def reset_daily_budget() -> dict[str, str]:
    """Reset daily LLM budget counter (called by beat)."""
    logger.info("daily_budget_reset")
    return {"status": "ok"}
