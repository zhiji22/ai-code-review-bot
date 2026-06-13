"""Unit tests for rate limiting via Redis sorted-set sliding window."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_mock_redis_pipeline(execute_return_value: list) -> tuple[MagicMock, MagicMock]:
    """Create a mock redis and pipeline pair.

    redis.asyncio.Redis.pipeline() returns a pipeline object where:
    - Queueing methods (zremrangebyscore, zcard, zadd, expire) are sync
    - execute() is async and returns the list of results
    """
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=execute_return_value)

    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe

    return mock_redis, mock_pipe


class TestCheckRateLimit:
    """Tests for check_rate_limit function."""

    @pytest.mark.asyncio
    async def test_check_rate_limit_within_limit(self) -> None:
        """When current count is below the limit, should return True."""
        from app.core.rate_limit import check_rate_limit

        mock_redis, mock_pipe = _make_mock_redis_pipeline(
            # zremrangebyscore result (unused), zcard result = 5, zadd result, expire result
            [0, 5, 1, 1]
        )

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            result = await check_rate_limit(key="rate:user:123", limit=10, window_seconds=60)

        assert result is True
        mock_redis.pipeline.assert_called_once()
        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self) -> None:
        """When current count >= limit, should raise HTTPException 429."""
        from app.core.rate_limit import check_rate_limit

        mock_redis, _mock_pipe = _make_mock_redis_pipeline(
            # zcard result = 10, which equals the limit of 10
            [0, 10, 1, 1]
        )

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await check_rate_limit(key="rate:user:456", limit=10, window_seconds=60)

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail
        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "60"
        assert exc_info.value.headers["X-RateLimit-Limit"] == "10"
        assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded_with_higher_count(self) -> None:
        """When count exceeds limit by a wide margin, still raises 429."""
        from app.core.rate_limit import check_rate_limit

        mock_redis, _mock_pipe = _make_mock_redis_pipeline([0, 500, 1, 1])

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await check_rate_limit(key="rate:user:789", limit=60, window_seconds=60)

        assert exc_info.value.status_code == 429
        assert "500/60" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_check_rate_limit_pipeline_operations(self) -> None:
        """Verify that the correct Redis pipeline commands are issued."""
        from app.core.rate_limit import check_rate_limit

        mock_redis, mock_pipe = _make_mock_redis_pipeline([0, 0, 1, 1])

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            await check_rate_limit(key="rate:test:ops", limit=5, window_seconds=30)

        # Verify the pipeline commands were called in order
        assert mock_pipe.zremrangebyscore.called
        assert mock_pipe.zcard.called
        assert mock_pipe.zadd.called
        assert mock_pipe.expire.called
        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_rate_limit_custom_window(self) -> None:
        """Rate limiting works with a custom window_seconds value."""
        from app.core.rate_limit import check_rate_limit

        mock_redis, _mock_pipe = _make_mock_redis_pipeline([0, 3, 1, 1])

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            result = await check_rate_limit(key="rate:user:custom", limit=100, window_seconds=300)

        assert result is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_zero_count(self) -> None:
        """When no prior requests exist (count=0), returns True."""
        from app.core.rate_limit import check_rate_limit

        mock_redis, _mock_pipe = _make_mock_redis_pipeline([0, 0, 1, 1])

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            result = await check_rate_limit(key="rate:user:new", limit=10, window_seconds=60)

        assert result is True


class TestGetRateLimitInfo:
    """Tests for get_rate_limit_info function."""

    @pytest.mark.asyncio
    async def test_get_rate_limit_info(self) -> None:
        """Returns dict with limit, remaining, and reset_at fields."""
        from app.core.rate_limit import get_rate_limit_info

        mock_redis, _mock_pipe = _make_mock_redis_pipeline(
            # zremrangebyscore result, zcard result = 7
            [0, 7]
        )

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            info = await get_rate_limit_info(key="rate:user:123", limit=10, window_seconds=60)

        assert info["limit"] == 10
        assert info["remaining"] == 3  # 10 - 7
        assert "reset_at" in info
        assert isinstance(info["reset_at"], int)

    @pytest.mark.asyncio
    async def test_get_rate_limit_info_zero_remaining(self) -> None:
        """When current count >= limit, remaining should be 0."""
        from app.core.rate_limit import get_rate_limit_info

        mock_redis, _mock_pipe = _make_mock_redis_pipeline(
            # zcard result = 15, exceeding the limit of 10
            [0, 15]
        )

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            info = await get_rate_limit_info(key="rate:user:maxed", limit=10, window_seconds=60)

        assert info["limit"] == 10
        assert info["remaining"] == 0  # max(0, 10 - 15) = 0
        assert "reset_at" in info

    @pytest.mark.asyncio
    async def test_get_rate_limit_info_no_prior_requests(self) -> None:
        """When no prior requests exist, remaining equals the full limit."""
        from app.core.rate_limit import get_rate_limit_info

        mock_redis, _mock_pipe = _make_mock_redis_pipeline([0, 0])

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            info = await get_rate_limit_info(key="rate:user:fresh", limit=100, window_seconds=120)

        assert info["limit"] == 100
        assert info["remaining"] == 100
        assert isinstance(info["reset_at"], int)

    @pytest.mark.asyncio
    async def test_get_rate_limit_info_does_not_increment(self) -> None:
        """get_rate_limit_info should NOT add a new entry (read-only)."""
        from app.core.rate_limit import get_rate_limit_info

        mock_redis, mock_pipe = _make_mock_redis_pipeline([0, 5])

        with patch("app.core.rate_limit.get_redis", return_value=mock_redis):
            await get_rate_limit_info(key="rate:user:readonly", limit=10, window_seconds=60)

        # Should NOT call zadd or expire -- only zremrangebyscore and zcard
        assert not mock_pipe.zadd.called
        assert not mock_pipe.expire.called
