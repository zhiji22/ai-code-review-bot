"""Unit tests for async idempotency functions (check, release, key building)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_mock_redis() -> MagicMock:
    """Create a mock redis.asyncio.Redis instance.

    get_redis() returns a sync object (redis.asyncio.Redis) where
    .set(), .delete() are async methods. Use MagicMock with specific
    async method mocks to avoid unawaited coroutine warnings.
    """
    mock_redis = MagicMock()
    mock_redis.set = AsyncMock()
    mock_redis.delete = AsyncMock()
    return mock_redis


class TestCheckIdempotency:
    """Tests for check_idempotency function."""

    @pytest.mark.asyncio
    async def test_check_idempotency_new_request(self) -> None:
        """When Redis SETNX returns truthy value, returns True (new request)."""
        from app.core.idempotency import check_idempotency

        mock_redis = _make_mock_redis()
        mock_redis.set.return_value = True

        with patch("app.core.idempotency.get_redis", return_value=mock_redis):
            result = await check_idempotency(key="webhook:pr:owner/repo:42:abc123")

        assert result is True
        mock_redis.set.assert_awaited_once_with(
            "webhook:pr:owner/repo:42:abc123", "1", nx=True, ex=3600
        )

    @pytest.mark.asyncio
    async def test_check_idempotency_duplicate(self) -> None:
        """When Redis SETNX returns None, raises HTTPException 409 (duplicate)."""
        from app.core.idempotency import check_idempotency

        mock_redis = _make_mock_redis()
        mock_redis.set.return_value = None

        with patch("app.core.idempotency.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException) as exc_info:
                await check_idempotency(key="webhook:pr:owner/repo:42:abc123")

        assert exc_info.value.status_code == 409
        assert "Duplicate webhook" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_check_idempotency_custom_ttl(self) -> None:
        """Verify that custom TTL is passed to Redis SET command."""
        from app.core.idempotency import check_idempotency

        mock_redis = _make_mock_redis()
        mock_redis.set.return_value = True

        with patch("app.core.idempotency.get_redis", return_value=mock_redis):
            result = await check_idempotency(key="test:key", ttl=7200)

        assert result is True
        mock_redis.set.assert_awaited_once_with("test:key", "1", nx=True, ex=7200)

    @pytest.mark.asyncio
    async def test_check_idempotency_default_ttl(self) -> None:
        """Default TTL should be 3600 seconds."""
        from app.core.idempotency import check_idempotency

        mock_redis = _make_mock_redis()
        mock_redis.set.return_value = True

        with patch("app.core.idempotency.get_redis", return_value=mock_redis):
            await check_idempotency(key="test:default_ttl")

        call_kwargs = mock_redis.set.call_args
        assert call_kwargs[1]["ex"] == 3600


class TestReleaseIdempotency:
    """Tests for release_idempotency function."""

    @pytest.mark.asyncio
    async def test_release_idempotency(self) -> None:
        """Calls Redis delete for the given key."""
        from app.core.idempotency import release_idempotency

        mock_redis = _make_mock_redis()
        mock_redis.delete.return_value = 1

        with patch("app.core.idempotency.get_redis", return_value=mock_redis):
            await release_idempotency(key="webhook:pr:owner/repo:42:abc123")

        mock_redis.delete.assert_awaited_once_with("webhook:pr:owner/repo:42:abc123")

    @pytest.mark.asyncio
    async def test_release_idempotency_nonexistent_key(self) -> None:
        """Deleting a key that does not exist should not raise an error."""
        from app.core.idempotency import release_idempotency

        mock_redis = _make_mock_redis()
        mock_redis.delete.return_value = 0

        with patch("app.core.idempotency.get_redis", return_value=mock_redis):
            await release_idempotency(key="webhook:pr:nonexistent:key")

        mock_redis.delete.assert_awaited_once()


class TestBuildWebhookIdempotencyKey:
    """Tests for build_webhook_idempotency_key (sync, additional edge cases)."""

    def test_key_exact_format(self) -> None:
        """Key should follow exact format: webhook:pr:{repo}:{pr_number}:{sha}."""
        from app.core.idempotency import build_webhook_idempotency_key

        key = build_webhook_idempotency_key(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123def456",
        )
        assert key == "webhook:pr:owner/repo:42:abc123def456"

    def test_key_with_special_characters_in_repo(self) -> None:
        """Repo name with hyphens, dots, and underscores is preserved exactly."""
        from app.core.idempotency import build_webhook_idempotency_key

        key = build_webhook_idempotency_key(
            repo_full_name="my-org.repo_v2",
            pr_number=1,
            commit_sha="sha",
        )
        assert key == "webhook:pr:my-org.repo_v2:1:sha"

    def test_key_with_long_commit_sha(self) -> None:
        """Full 40-character SHA is preserved in the key."""
        from app.core.idempotency import build_webhook_idempotency_key

        long_sha = "a" * 40
        key = build_webhook_idempotency_key(
            repo_full_name="owner/repo",
            pr_number=999,
            commit_sha=long_sha,
        )
        assert key == f"webhook:pr:owner/repo:999:{long_sha}"

    def test_key_with_nested_org_path(self) -> None:
        """Repo full name with multiple slashes is preserved."""
        from app.core.idempotency import build_webhook_idempotency_key

        key = build_webhook_idempotency_key(
            repo_full_name="org/subgroup/repo",
            pr_number=5,
            commit_sha="deadbeef",
        )
        assert key == "webhook:pr:org/subgroup/repo:5:deadbeef"
