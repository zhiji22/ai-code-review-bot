"""Unit tests for the LLM budget control service.

The budget_service module has a module-level instantiation (line 118):
    budget_service = BudgetService()
which reads settings.llm_budget_per_pr_tokens. The Settings class defines
llm_budget_max_tokens_per_pr instead, so importing the module fails at the
module-level singleton.

Strategy: Patch app.core.config.settings before the first import of
budget_service so the module-level code succeeds. After that, individual
tests create fresh BudgetService instances and mock get_redis as needed.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level import with patched settings.
# We patch app.core.config.settings BEFORE importing budget_service so that
# the module-level `budget_service = BudgetService()` does not crash.
# This happens once when the test file is collected.
# ---------------------------------------------------------------------------
_mock_settings_for_import = MagicMock()
_mock_settings_for_import.llm_budget_daily_usd = 50.0
_mock_settings_for_import.llm_budget_max_tokens_per_pr = 500_000

with patch("app.core.config.settings", _mock_settings_for_import):
    from app.services.budget_service import BudgetExceededError, BudgetService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_settings(
    daily_usd: float = 50.0,
    per_pr_tokens: int = 500_000,
) -> MagicMock:
    """Create a mock settings with budget limit attributes."""
    mock_settings = MagicMock()
    mock_settings.llm_budget_daily_usd = daily_usd
    mock_settings.llm_budget_max_tokens_per_pr = per_pr_tokens
    return mock_settings


def _make_mock_redis(
    get_side_effect=None,
    get_return_value=None,
) -> MagicMock:
    """Create a mock redis suitable for budget_service.

    budget_service calls:
      - await get_redis()        -> AsyncMock returning redis
      - await redis.get(key)     -> redis.get must be AsyncMock
      - redis.pipeline()         -> sync, returns a pipeline
      - pipe.incrby(...)         -> sync pipeline queueing
      - pipe.incrbyfloat(...)    -> sync pipeline queueing
      - pipe.expire(...)         -> sync pipeline queueing
      - await pipe.execute()     -> async pipeline execution
    """
    mock_redis = MagicMock()
    if get_side_effect is not None:
        mock_redis.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock_redis.get = AsyncMock(return_value=get_return_value)
    return mock_redis


def _make_mock_pipeline(execute_return=None) -> MagicMock:
    """Create a mock Redis pipeline with async execute."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=execute_return or [])
    return mock_pipe


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestBudgetServiceInit:
    """Tests for BudgetService initialization."""

    def test_init_reads_settings(self) -> None:
        """BudgetService reads limits from settings on init."""
        mock_settings = _make_mock_settings(daily_usd=100.0, per_pr_tokens=1_000_000)
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        assert svc.daily_limit_usd == 100.0
        assert svc.pr_limit_tokens == 1_000_000

    def test_init_default_settings(self) -> None:
        """BudgetService uses default settings values."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        assert svc.daily_limit_usd == 50.0
        assert svc.pr_limit_tokens == 500_000


class TestCheckBudget:
    """Tests for check_budget method."""

    @pytest.mark.asyncio
    async def test_check_budget_within_limits(self) -> None:
        """When both daily cost and per-PR tokens are within limits, returns True."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        today = date.today().isoformat()

        async def mock_get(key: str) -> str | None:
            if today in key and "cost" in key:
                return "10.5"
            if "pr_tokens" in key:
                return "100000"
            return None

        mock_redis = _make_mock_redis(get_side_effect=mock_get)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await svc.check_budget(repo="owner/repo", pr_number=42, commit_sha="abc123")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_budget_daily_exceeded(self) -> None:
        """Raises BudgetExceededError when daily cost >= limit."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        today = date.today().isoformat()
        daily_cost_key = f"budget:cost:{today}"

        async def mock_get(key: str) -> str | None:
            if key == daily_cost_key:
                return "55.0"
            return None

        mock_redis = _make_mock_redis(get_side_effect=mock_get)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            with pytest.raises(BudgetExceededError) as exc_info:
                await svc.check_budget(repo="owner/repo", pr_number=42, commit_sha="abc123")

        assert "Daily LLM budget exceeded" in str(exc_info.value)
        assert exc_info.value.current == 55.0
        assert exc_info.value.limit == 50.0

    @pytest.mark.asyncio
    async def test_check_budget_per_pr_exceeded(self) -> None:
        """Raises BudgetExceededError when per-PR tokens >= limit."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        async def mock_get(key: str) -> str | None:
            if "cost" in key:
                return "5.0"
            if "pr_tokens" in key:
                return "600000"
            return None

        mock_redis = _make_mock_redis(get_side_effect=mock_get)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            with pytest.raises(BudgetExceededError) as exc_info:
                await svc.check_budget(repo="owner/repo", pr_number=99, commit_sha="def456")

        assert "Per-PR token budget exceeded" in str(exc_info.value)
        assert exc_info.value.current == 600000.0
        assert exc_info.value.limit == 500_000.0

    @pytest.mark.asyncio
    async def test_check_budget_no_prior_usage(self) -> None:
        """When no prior usage exists (Redis returns None), returns True."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        mock_redis = _make_mock_redis(get_return_value=None)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await svc.check_budget(repo="owner/repo", pr_number=1, commit_sha="sha000")

        assert result is True

    @pytest.mark.asyncio
    async def test_check_budget_daily_exactly_at_limit(self) -> None:
        """When daily cost exactly equals limit, raises BudgetExceededError."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        today = date.today().isoformat()
        daily_cost_key = f"budget:cost:{today}"

        async def mock_get(key: str) -> str | None:
            if key == daily_cost_key:
                return "50.0"
            return None

        mock_redis = _make_mock_redis(get_side_effect=mock_get)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            with pytest.raises(BudgetExceededError) as exc_info:
                await svc.check_budget(repo="owner/repo", pr_number=42, commit_sha="abc123")

        assert exc_info.value.current == 50.0


class TestRecordUsage:
    """Tests for record_usage method."""

    @pytest.mark.asyncio
    async def test_record_usage(self) -> None:
        """Records tokens and cost via Redis pipeline."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        mock_pipe = _make_mock_pipeline(execute_return=[1000, 0.05, 1000, 1, 1, 1])
        mock_redis = _make_mock_redis()
        mock_redis.pipeline.return_value = mock_pipe

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            await svc.record_usage(
                repo="owner/repo",
                pr_number=42,
                commit_sha="abc123",
                tokens=1500,
                cost_usd=0.08,
            )

        mock_redis.pipeline.assert_called_once()
        assert mock_pipe.incrby.call_count == 2
        mock_pipe.incrbyfloat.assert_called_once()
        assert mock_pipe.expire.call_count == 3
        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_usage_zero_cost(self) -> None:
        """Recording zero cost and tokens should still execute pipeline."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        mock_pipe = _make_mock_pipeline(execute_return=[0, 0.0, 0, 1, 1, 1])
        mock_redis = _make_mock_redis()
        mock_redis.pipeline.return_value = mock_pipe

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            await svc.record_usage(
                repo="owner/repo",
                pr_number=1,
                commit_sha="zero",
                tokens=0,
                cost_usd=0.0,
            )

        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_usage_key_format(self) -> None:
        """Verify the correct Redis key patterns are used."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        mock_pipe = _make_mock_pipeline(execute_return=[500, 0.03, 500, 1, 1, 1])
        mock_redis = _make_mock_redis()
        mock_redis.pipeline.return_value = mock_pipe

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            await svc.record_usage(
                repo="myorg/myrepo",
                pr_number=7,
                commit_sha="deadbeef",
                tokens=500,
                cost_usd=0.03,
            )

        today = date.today().isoformat()

        incrby_calls = mock_pipe.incrby.call_args_list
        daily_tokens_call = incrby_calls[0]
        assert f"budget:tokens:{today}" in daily_tokens_call[0][0]

        pr_tokens_call = incrby_calls[1]
        assert "budget:pr_tokens:myorg/myrepo:7:deadbeef" in pr_tokens_call[0][0]

        cost_call = mock_pipe.incrbyfloat.call_args
        assert f"budget:cost:{today}" in cost_call[0][0]


class TestGetDailyUsage:
    """Tests for get_daily_usage method."""

    @pytest.mark.asyncio
    async def test_get_daily_usage(self) -> None:
        """Returns usage snapshot with cost, tokens, and limits."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        today = date.today().isoformat()

        async def mock_get(key: str) -> str | None:
            if "cost" in key:
                return "25.75"
            if "tokens" in key:
                return "150000"
            return None

        mock_redis = _make_mock_redis(get_side_effect=mock_get)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            usage = await svc.get_daily_usage()

        assert usage["date"] == today
        assert usage["cost_usd"] == 25.75
        assert usage["tokens"] == 150000
        assert usage["limit_usd"] == 50.0
        assert usage["remaining_usd"] == 24.25
        assert usage["limit_tokens_per_pr"] == 500_000

    @pytest.mark.asyncio
    async def test_get_daily_usage_empty(self) -> None:
        """When no usage recorded yet, returns zeros for cost and tokens."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        today = date.today().isoformat()

        mock_redis = _make_mock_redis(get_return_value=None)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            usage = await svc.get_daily_usage()

        assert usage["date"] == today
        assert usage["cost_usd"] == 0.0
        assert usage["tokens"] == 0
        assert usage["limit_usd"] == 50.0
        assert usage["remaining_usd"] == 50.0

    @pytest.mark.asyncio
    async def test_get_daily_usage_exceeded(self) -> None:
        """When usage exceeds limit, remaining_usd should be clamped to 0."""
        mock_settings = _make_mock_settings()
        with patch("app.services.budget_service.settings", mock_settings):
            svc = BudgetService()

        async def mock_get(key: str) -> str | None:
            if "cost" in key:
                return "75.0"
            if "tokens" in key:
                return "800000"
            return None

        mock_redis = _make_mock_redis(get_side_effect=mock_get)

        with patch("app.services.budget_service.get_redis", new=AsyncMock(return_value=mock_redis)):
            usage = await svc.get_daily_usage()

        assert usage["cost_usd"] == 75.0
        assert usage["remaining_usd"] == 0.0
