"""
Celery application configuration.

Per DESIGN.md §3 + §9: Celery with Redis broker, retry/timeout/backoff.
"""

from __future__ import annotations

import structlog
from celery import Celery
from celery.signals import task_failure, task_success, worker_process_init
from typing import Any

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

settings = get_settings()

celery_app = Celery(
    "ai_code_review_bot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Performance
    worker_concurrency=settings.celery_worker_concurrency,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    task_acks_late=settings.celery_task_acks_late,
    # Timeouts
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    # Retries
    task_default_max_retries=settings.celery_task_max_retries,
    task_default_retry_delay=settings.celery_task_default_retry_delay,
    # Reliability
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=5,
    # Results
    result_expires=86400,  # 24 hours
    task_track_started=True,
    # Beat schedule
    beat_schedule={
        "cleanup-expired-idempotency": {
            "task": "app.tasks.review_tasks.cleanup_expired_keys",
            "schedule": 3600,  # Every hour
        },
        "daily-llm-budget-reset": {
            "task": "app.tasks.review_tasks.reset_daily_budget",
            "schedule": 86400,  # Daily
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])


@task_success.connect  # type: ignore[misc]
def on_task_success(sender: Any, **kwargs: Any) -> None:
    logger.info("task_completed", task=sender.name, task_id=sender.request.id)


@task_failure.connect  # type: ignore[misc]
def on_task_failure(sender: Any, exception: BaseException, **kwargs: Any) -> None:
    logger.error(
        "task_failed",
        task=sender.name,
        task_id=sender.request.id,
        error=str(exception),
    )


# Clear module-level caches after Celery prefork so each child starts fresh
@worker_process_init.connect  # type: ignore[misc]
def _on_worker_process_init(**kwargs: Any) -> None:
    # Reset GitHub client module-level caches inherited from parent process
    import app.services.github_client as gh_mod

    gh_mod._cached_private_key = None
    gh_mod._token_cache = {}
