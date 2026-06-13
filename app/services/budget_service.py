"""LLM budget control service.

Tracks daily USD spend and per-PR token usage against limits.
Per DESIGN.md §13: prevent OpenAI cost overruns.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog

from app.core.config import settings
from app.core.redis import get_redis

logger = structlog.get_logger()


class BudgetExceededError(Exception):
    """Raised when LLM budget is exhausted."""

    def __init__(self, message: str, current: float, limit: float):
        super().__init__(message)
        self.current = current
        self.limit = limit


class BudgetService:
    """Track and enforce LLM spending limits using Redis."""

    DAILY_COST_KEY = "budget:cost:{date}"
    DAILY_TOKENS_KEY = "budget:tokens:{date}"
    PR_TOKENS_KEY = "budget:pr_tokens:{repo}:{pr}:{sha}"

    def __init__(self) -> None:
        self.daily_limit_usd = settings.llm_budget_daily_usd
        self.pr_limit_tokens = settings.llm_budget_max_tokens_per_pr

    async def check_budget(self, repo: str, pr_number: int, commit_sha: str) -> bool:
        """Return True if within budget, raise BudgetExceededError if not."""
        redis = await get_redis()
        today = date.today().isoformat()

        # Check daily USD
        daily_cost = await redis.get(self.DAILY_COST_KEY.format(date=today))
        daily_cost = float(daily_cost) if daily_cost else 0.0
        if daily_cost >= self.daily_limit_usd:
            raise BudgetExceededError(
                f"Daily LLM budget exceeded: ${daily_cost:.2f} / ${self.daily_limit_usd:.2f}",
                current=daily_cost,
                limit=self.daily_limit_usd,
            )

        # Check per-PR tokens
        pr_key = self.PR_TOKENS_KEY.format(repo=repo, pr=pr_number, sha=commit_sha)
        pr_tokens = await redis.get(pr_key)
        pr_tokens = int(pr_tokens) if pr_tokens else 0
        if pr_tokens >= self.pr_limit_tokens:
            raise BudgetExceededError(
                f"Per-PR token budget exceeded: {pr_tokens} / {self.pr_limit_tokens}",
                current=float(pr_tokens),
                limit=float(self.pr_limit_tokens),
            )

        return True

    async def record_usage(
        self,
        repo: str,
        pr_number: int,
        commit_sha: str,
        tokens: int,
        cost_usd: float,
    ) -> None:
        """Record token/cost usage after an LLM call."""
        redis = await get_redis()
        today = date.today().isoformat()

        pipe = redis.pipeline()
        pipe.incrby(self.DAILY_TOKENS_KEY.format(date=today), tokens)
        pipe.incrbyfloat(self.DAILY_COST_KEY.format(date=today), cost_usd)
        pipe.incrby(
            self.PR_TOKENS_KEY.format(repo=repo, pr=pr_number, sha=commit_sha),
            tokens,
        )
        # TTL: daily keys expire after 48h, PR keys after 1h
        pipe.expire(self.DAILY_TOKENS_KEY.format(date=today), 172800)
        pipe.expire(self.DAILY_COST_KEY.format(date=today), 172800)
        pipe.expire(self.PR_TOKENS_KEY.format(repo=repo, pr=pr_number, sha=commit_sha), 3600)
        await pipe.execute()

        logger.info(
            "budget.recorded",
            repo=repo,
            pr=pr_number,
            tokens=tokens,
            cost_usd=cost_usd,
            daily_total_cost=cost_usd,
        )

    async def get_daily_usage(self) -> dict[str, Any]:
        """Get today's usage snapshot for dashboard."""
        redis = await get_redis()
        today = date.today().isoformat()

        daily_cost = await redis.get(self.DAILY_COST_KEY.format(date=today))
        daily_tokens = await redis.get(self.DAILY_TOKENS_KEY.format(date=today))

        return {
            "date": today,
            "cost_usd": float(daily_cost) if daily_cost else 0.0,
            "tokens": int(daily_tokens) if daily_tokens else 0,
            "limit_usd": self.daily_limit_usd,
            "limit_tokens_per_pr": self.pr_limit_tokens,
            "remaining_usd": max(0, self.daily_limit_usd - float(daily_cost or 0)),
        }


budget_service = BudgetService()
