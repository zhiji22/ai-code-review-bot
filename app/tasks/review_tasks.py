"""
Celery review tasks — async PR review pipeline.

Per DESIGN.md §3: Review Engine runs as Celery task with retry/timeout/backoff.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import httpx
import structlog
from celery import Task
from sqlalchemy import select

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


class ReviewTask(Task):  # type: ignore[misc]
    """Base task class with custom error handling."""

    autoretry_for: ClassVar[tuple[type[Exception], ...]] = (
        httpx.HTTPStatusError,
        httpx.ConnectError,
        httpx.TimeoutException,
    )
    retry_kwargs: ClassVar[dict[str, Any]] = {"max_retries": 3}
    retry_backoff: ClassVar[bool] = True  # Exponential backoff
    retry_backoff_max: ClassVar[int] = 300  # 5 minutes
    retry_jitter: ClassVar[bool] = True


@celery_app.task(  # type: ignore[misc]
    base=ReviewTask,
    name="app.tasks.review_tasks.queue_pr_review",
    bind=True,
)
def queue_pr_review(
    self: ReviewTask,
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
    7. Persist results to database

    Returns:
        Review summary dict.
    """
    import time

    from app.core.database import get_db_session
    from app.core.review_engine import ReviewEngine
    from app.models.repository import Repository
    from app.services.github_client import get_github_client
    from app.services.review_service import ReviewService

    # Create authenticated GitHub client
    client = await get_github_client(installation_id=installation_id)

    try:
        start = time.time()
        engine = ReviewEngine()
        result = await engine.review_pull_request(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            commit_sha=commit_sha,
            github_client=client,
        )
        duration_ms = int((time.time() - start) * 1000)

        logger.info(
            "review_pipeline_completed",
            repo=repo_full_name,
            pr_number=pr_number,
            success=result.success,
            issues=result.aggregated.total_issues,
        )

        # Extract PR info for persistence
        pr_info = await client.get_pr_info(repo_full_name, pr_number)

        # Persist to database
        async with get_db_session() as session:
            stmt = select(Repository).where(
                Repository.full_name == repo_full_name
            )
            repo_result = await session.execute(stmt)
            repo = repo_result.scalar_one_or_none()

            if repo is None:
                parts = repo_full_name.split("/")
                repo = Repository(
                    github_repo_id=abs(hash(repo_full_name)) % (10**9),
                    full_name=repo_full_name,
                    owner=parts[0] if len(parts) == 2 else "",
                    name=parts[1] if len(parts) == 2 else repo_full_name,
                    installation_id=installation_id,
                )
                session.add(repo)
                await session.flush()

            service = ReviewService(session)
            agg = result.aggregated

            review = await service.create_from_pipeline(
                repository_id=repo.id,
                pr_number=pr_number,
                commit_sha=commit_sha,
                pr_title=pr_info.title,
                pr_author=pr_info.author,
                trigger="webhook",
                files_reviewed=agg.files_reviewed,
                files_total=pr_info.changed_files,
                lines_of_code=agg.lines_of_code,
                overall_score=agg.scores.overall,
                security_score=agg.scores.security,
                performance_score=agg.scores.performance,
                maintainability_score=agg.scores.maintainability,
                critical_count=agg.critical_count,
                warning_count=agg.warning_count,
                info_count=agg.info_count,
                llm_tokens_total=agg.llm_tokens,
                llm_cost_usd=agg.llm_cost_usd,
                duration_ms=duration_ms,
                summary=agg.summary,
                pr_comment_posted=bool(result.pr_comment),
                inline_comments_posted=result.inline_comments_count,
            )

            # Save comments
            comments_data = [
                {
                    "file_path": issue.file_path,
                    "line_number": issue.line_number,
                    "line_end": issue.line_end,
                    "source": issue.source,
                    "category": issue.category,
                    "severity": issue.severity,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "rule_id": issue.rule_id,
                    "confidence": issue.confidence,
                }
                for issue in agg.issues
            ]
            if comments_data:
                await service.save_comments(review.id, comments_data)

            logger.info(
                "review_persisted",
                review_id=review.id,
                repo=repo_full_name,
                pr_number=pr_number,
            )

        return {
            "success": result.success,
            "repo_full_name": result.repo_full_name,
            "pr_number": result.pr_number,
            "commit_sha": result.commit_sha,
            "error": result.error,
            "overall_score": result.aggregated.scores.overall,
            "total_issues": result.aggregated.total_issues,
            "critical_count": result.aggregated.critical_count,
            "inline_comments_count": result.inline_comments_count,
        }
    finally:
        await client.close()


@celery_app.task(name="app.tasks.review_tasks.cleanup_expired_keys")  # type: ignore[misc]
def cleanup_expired_keys() -> dict[str, Any]:
    """Clean up expired idempotency/rate-limit keys (called by beat)."""
    logger.info("cleanup_task_running")
    # Redis handles TTL automatically; this is a no-op placeholder
    return {"status": "ok", "cleaned": 0}


@celery_app.task(name="app.tasks.review_tasks.reset_daily_budget")  # type: ignore[misc]
def reset_daily_budget() -> dict[str, str]:
    """Reset daily LLM budget counter (called by beat)."""
    logger.info("daily_budget_reset")
    return {"status": "ok"}
