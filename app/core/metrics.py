"""Prometheus custom metrics for the AI Code Review Bot.

Exposes counters and histograms for webhook, review pipeline, LLM usage,
and GitHub API interactions.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )
except ImportError:
    # Fallback if prometheus_client not installed
    Counter = Histogram = Gauge = Info = None
    generate_latest = lambda: b""  # noqa: E731
    CONTENT_TYPE_LATEST = "text/plain"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Webhook metrics
# ---------------------------------------------------------------------------
WEBHOOK_REQUESTS = Counter(
    "review_webhook_requests_total",
    "Total webhook requests received",
    ["event", "action", "status"],
)

WEBHOOK_PROCESSING_TIME = Histogram(
    "review_webhook_processing_seconds",
    "Time spent processing webhook (verification + queue)",
    ["event"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

WEBHOOK_DUPLICATES = Counter(
    "review_webhook_duplicates_total",
    "Duplicate webhook deliveries rejected",
    ["event"],
)

# ---------------------------------------------------------------------------
# Review pipeline metrics
# ---------------------------------------------------------------------------
REVIEW_TOTAL = Counter(
    "review_pipeline_total",
    "Total reviews completed",
    ["repository", "status"],  # status: success, failed, partial
)

REVIEW_DURATION = Histogram(
    "review_pipeline_duration_seconds",
    "End-to-end review duration",
    ["repository"],
    buckets=(1, 2.5, 5, 10, 25, 50, 100, 250, 500),
)

REVIEW_FILES = Histogram(
    "review_files_per_pr",
    "Number of files analyzed per PR",
    ["repository"],
    buckets=(1, 5, 10, 20, 50, 100, 200, 500),
)

REVIEW_SCORE = Histogram(
    "review_score_distribution",
    "Overall review score distribution (0-100)",
    ["repository"],
    buckets=(10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)

ISSUES_FOUND = Counter(
    "review_issues_found_total",
    "Total issues found by analyzer",
    ["repository", "source", "severity"],  # source: rule/ast/llm
)

# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------
LLM_CALLS = Counter(
    "review_llm_calls_total",
    "Total LLM API calls",
    ["model", "status"],  # status: success, error, cached, timeout
)

LLM_TOKENS = Counter(
    "review_llm_tokens_total",
    "Total LLM tokens used",
    ["model", "type"],  # type: prompt, completion
)

LLM_COST = Counter(
    "review_llm_cost_usd_total",
    "Total LLM cost in USD",
    ["model"],
)

LLM_LATENCY = Histogram(
    "review_llm_latency_seconds",
    "LLM call latency",
    ["model"],
    buckets=(0.5, 1, 2.5, 5, 10, 25, 50, 100),
)

LLM_CACHE_HITS = Counter(
    "review_llm_cache_hits_total",
    "LLM cache hits (skipped API call)",
)

# ---------------------------------------------------------------------------
# GitHub API metrics
# ---------------------------------------------------------------------------
GITHUB_API_CALLS = Counter(
    "review_github_api_calls_total",
    "Total GitHub API calls",
    ["endpoint", "status"],
)

GITHUB_RATE_LIMIT_REMAINING = Gauge(
    "review_github_rate_limit_remaining",
    "GitHub API rate limit remaining",
)

# ---------------------------------------------------------------------------
# Queue / worker metrics
# ---------------------------------------------------------------------------
CELERY_QUEUE_LENGTH = Gauge(
    "review_celery_queue_length",
    "Celery pending tasks",
    ["queue"],
)

ACTIVE_REVIEWS = Gauge(
    "review_active_count",
    "Currently in-progress reviews",
)

# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------
APP_INFO = Info(
    "review_bot",
    "AI Code Review Bot application info",
)

BUDGET_UTILIZATION = Gauge(
    "review_budget_utilization_ratio",
    "Daily LLM budget utilization (0-1)",
    ["period"],  # period: daily
)


def init_metrics() -> None:
    """Initialize metrics with static info. Call once at startup."""
    if APP_INFO is None:
        return
    APP_INFO.info(
        {
            "version": "1.0.0",
            "name": "ai-code-review-bot",
        }
    )
    logger.info("Prometheus metrics initialized")


def get_metrics() -> tuple[bytes, str]:
    """Return latest metrics bytes and content type for /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST


def record_llm_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    cached: bool = False,
    duration_s: float | None = None,
    error: str | None = None,
) -> None:
    """Helper to record LLM metrics in one call."""
    if LLM_CALLS is None:
        return
    status = "cached" if cached else ("error" if error else "success")
    LLM_CALLS.labels(model=model, status=status).inc()
    if not cached:
        LLM_TOKENS.labels(model=model, type="prompt").inc(prompt_tokens)
        LLM_TOKENS.labels(model=model, type="completion").inc(completion_tokens)
        LLM_COST.labels(model=model).inc(cost_usd)
        if duration_s is not None:
            LLM_LATENCY.labels(model=model).observe(duration_s)
    else:
        LLM_CACHE_HITS.inc()


def record_review_complete(
    repo: str,
    status: str,
    duration_s: float,
    file_count: int,
    score: float,
    issue_counts: dict[str, dict[str, int]] | None = None,
) -> None:
    """Helper to record review completion metrics in one call."""
    if REVIEW_TOTAL is None:
        return
    REVIEW_TOTAL.labels(repository=repo, status=status).inc()
    REVIEW_DURATION.labels(repository=repo).observe(duration_s)
    REVIEW_FILES.labels(repository=repo).observe(file_count)
    REVIEW_SCORE.labels(repository=repo).observe(score)
    if issue_counts:
        for source, severities in issue_counts.items():
            for severity, count in severities.items():
                if count:
                    ISSUES_FOUND.labels(
                        repository=repo,
                        source=source,
                        severity=severity,
                    ).inc(count)


def record_github_api(endpoint: str, status: int | str) -> None:
    """Record a GitHub API call."""
    if GITHUB_API_CALLS is None:
        return
    GITHUB_API_CALLS.labels(endpoint=endpoint, status=str(status)).inc()
