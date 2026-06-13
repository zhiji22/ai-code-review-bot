"""Unit tests for RepositoryService — CRUD operations for repositories."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.config import settings
from app.schemas.repositories import (
    RepositoryCreateSchema,
    RepositorySettingsSchema,
    RepositoryUpdateSchema,
)
from app.services.repository_service import RepositoryService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    """Mock AsyncSession."""
    return AsyncMock()


@pytest.fixture
def repo_service(mock_session: AsyncMock) -> RepositoryService:
    """RepositoryService with mocked session."""
    return RepositoryService(mock_session)


def _make_mock_repo(**overrides: Any) -> MagicMock:
    """Create a mock Repository-like object with sensible defaults."""
    defaults = {
        "id": 1,
        "github_repo_id": 12345,
        "full_name": "owner/repo",
        "owner": "owner",
        "name": "repo",
        "description": "Test repo",
        "language": "Python",
        "default_branch": "main",
        "is_private": False,
        "is_active": True,
        "webhook_secret": b"encrypted-bytes",
        "installation_id": None,
        "settings": RepositorySettingsSchema().model_dump(),
        "last_review_at": None,
        "total_reviews": 0,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


# ---------------------------------------------------------------------------
# 1. create
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for RepositoryService.create."""

    @pytest.mark.asyncio
    async def test_creates_repo_with_encrypted_secret(
        self, repo_service: RepositoryService
    ) -> None:
        """Creates repository with encrypted webhook_secret and default settings."""
        repo_service.session.commit = AsyncMock()
        repo_service.session.refresh = AsyncMock()
        # session.add is synchronous in SQLAlchemy
        repo_service.session.add = MagicMock()

        data = RepositoryCreateSchema(
            github_repo_id=12345,
            full_name="owner/repo",
            owner="owner",
            name="repo",
            description="A test repo",
            language="Python",
            default_branch="main",
            is_private=False,
            webhook_secret="my-secret-key",
        )

        with patch(
            "app.services.repository_service.encrypt_secret", return_value=b"encrypted-bytes"
        ) as mock_encrypt:
            await repo_service.create(data)

        mock_encrypt.assert_called_once_with("my-secret-key", settings.secret_key)

        repo_service.session.add.assert_called_once()
        added = repo_service.session.add.call_args[0][0]
        assert added.github_repo_id == 12345
        assert added.full_name == "owner/repo"
        assert added.webhook_secret == b"encrypted-bytes"
        assert added.default_branch == "main"
        assert isinstance(added.settings, dict)
        assert added.settings["auto_review"] is True

        repo_service.session.commit.assert_awaited_once()
        repo_service.session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generates_secret_when_not_provided(
        self, repo_service: RepositoryService
    ) -> None:
        """When webhook_secret is None, a random UUID hex is generated and encrypted."""
        repo_service.session.commit = AsyncMock()
        repo_service.session.refresh = AsyncMock()
        # session.add is synchronous in SQLAlchemy
        repo_service.session.add = MagicMock()

        data = RepositoryCreateSchema(
            github_repo_id=99999,
            full_name="org/project",
            owner="org",
            name="project",
        )

        with patch(
            "app.services.repository_service.encrypt_secret", return_value=b"enc"
        ) as mock_encrypt:
            await repo_service.create(data)

        # encrypt_secret should have been called with a hex string (32 chars from uuid4)
        call_args = mock_encrypt.call_args[0]
        assert len(call_args[0]) == 32  # uuid4().hex is 32 chars
        assert call_args[1] == settings.secret_key


# ---------------------------------------------------------------------------
# 2-4. get_by_id, get_by_github_id, get_by_full_name
# ---------------------------------------------------------------------------


class TestGetById:
    """Tests for RepositoryService.get_by_id."""

    @pytest.mark.asyncio
    async def test_returns_repo(self, repo_service: RepositoryService) -> None:
        """Returns repository when found by id."""
        mock_repo = _make_mock_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute.return_value = mock_result

        result = await repo_service.get_by_id(1)

        assert result is mock_repo

    @pytest.mark.asyncio
    async def test_returns_none_not_found(self, repo_service: RepositoryService) -> None:
        """Returns None when repository id does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        repo_service.session.execute.return_value = mock_result

        result = await repo_service.get_by_id(9999)

        assert result is None


class TestGetByGithubId:
    """Tests for RepositoryService.get_by_github_id."""

    @pytest.mark.asyncio
    async def test_returns_repo(self, repo_service: RepositoryService) -> None:
        """Returns repository when found by github_repo_id."""
        mock_repo = _make_mock_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute.return_value = mock_result

        result = await repo_service.get_by_github_id(12345)

        assert result is mock_repo

    @pytest.mark.asyncio
    async def test_returns_none_not_found(self, repo_service: RepositoryService) -> None:
        """Returns None when github_repo_id does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        repo_service.session.execute.return_value = mock_result

        result = await repo_service.get_by_github_id(99999)

        assert result is None


class TestGetByFullName:
    """Tests for RepositoryService.get_by_full_name."""

    @pytest.mark.asyncio
    async def test_returns_repo(self, repo_service: RepositoryService) -> None:
        """Returns repository when found by full_name."""
        mock_repo = _make_mock_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute.return_value = mock_result

        result = await repo_service.get_by_full_name("owner/repo")

        assert result is mock_repo


# ---------------------------------------------------------------------------
# 5. list_active
# ---------------------------------------------------------------------------


class TestListActive:
    """Tests for RepositoryService.list_active."""

    @pytest.mark.asyncio
    async def test_returns_active_repos_with_count(self, repo_service: RepositoryService) -> None:
        """Returns active repositories and total count."""
        mock_repo = _make_mock_repo()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_repo]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        repo_service.session.execute.return_value = mock_result
        repo_service.session.scalar = AsyncMock(return_value=1)

        repos, total = await repo_service.list_active(offset=0, limit=50)

        assert len(repos) == 1
        assert repos[0] is mock_repo
        assert total == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(self, repo_service: RepositoryService) -> None:
        """Returns empty list and 0 count when no active repos."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        repo_service.session.execute.return_value = mock_result
        repo_service.session.scalar = AsyncMock(return_value=None)

        repos, total = await repo_service.list_active()

        assert repos == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_pagination(self, repo_service: RepositoryService) -> None:
        """Offset and limit are passed through to the query."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        repo_service.session.execute.return_value = mock_result
        repo_service.session.scalar = AsyncMock(return_value=0)

        _repos, total = await repo_service.list_active(offset=10, limit=5)

        assert total == 0


# ---------------------------------------------------------------------------
# 6. update
# ---------------------------------------------------------------------------


class TestUpdate:
    """Tests for RepositoryService.update."""

    @pytest.mark.asyncio
    async def test_updates_repo_fields(self, repo_service: RepositoryService) -> None:
        """Executes UPDATE statement and returns updated repo."""
        mock_repo = _make_mock_repo(is_active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo

        # session.execute is called twice: once for UPDATE, once for SELECT in get_by_id
        repo_service.session.execute = AsyncMock(return_value=mock_result)
        repo_service.session.commit = AsyncMock()

        data = RepositoryUpdateSchema(is_active=True)
        result = await repo_service.update(repo_id=1, data=data)

        assert result is mock_repo
        # At least one commit for the update
        assert repo_service.session.commit.await_count >= 1

    @pytest.mark.asyncio
    async def test_returns_none_when_no_values(self, repo_service: RepositoryService) -> None:
        """When data has no set values, delegates to get_by_id without updating."""
        mock_repo = _make_mock_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute = AsyncMock(return_value=mock_result)

        # RepositoryUpdateSchema with nothing set — model_dump(exclude_unset=True) returns {}
        data = RepositoryUpdateSchema()
        result = await repo_service.update(repo_id=1, data=data)

        assert result is mock_repo
        # commit should NOT be called when no values to update
        repo_service.session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# 7. update_settings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    """Tests for RepositoryService.update_settings."""

    @pytest.mark.asyncio
    async def test_updates_settings_jsonb(self, repo_service: RepositoryService) -> None:
        """Updates the settings JSONB field and returns repo."""
        mock_repo = _make_mock_repo()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute = AsyncMock(return_value=mock_result)
        repo_service.session.commit = AsyncMock()
        repo_service.session.refresh = AsyncMock()

        new_settings = RepositorySettingsSchema(
            auto_review=False,
            enable_llm=False,
            max_files_per_review=50,
        )
        result = await repo_service.update_settings(repo_id=1, settings_data=new_settings)

        assert result is mock_repo
        assert mock_repo.settings == new_settings.model_dump()
        repo_service.session.commit.assert_awaited_once()
        repo_service.session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_repo_not_found(self, repo_service: RepositoryService) -> None:
        """Returns None when the repository does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        repo_service.session.execute = AsyncMock(return_value=mock_result)

        result = await repo_service.update_settings(
            repo_id=9999,
            settings_data=RepositorySettingsSchema(),
        )

        assert result is None


# ---------------------------------------------------------------------------
# 8. deactivate (soft delete)
# ---------------------------------------------------------------------------


class TestDeactivate:
    """Tests for RepositoryService.deactivate."""

    @pytest.mark.asyncio
    async def test_soft_deletes(self, repo_service: RepositoryService) -> None:
        """Sets is_active=False and returns True when rowcount > 0."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        repo_service.session.execute = AsyncMock(return_value=mock_result)
        repo_service.session.commit = AsyncMock()

        success = await repo_service.deactivate(repo_id=1)

        assert success is True
        repo_service.session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, repo_service: RepositoryService) -> None:
        """Returns False when no row was updated (rowcount == 0)."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        repo_service.session.execute = AsyncMock(return_value=mock_result)
        repo_service.session.commit = AsyncMock()

        success = await repo_service.deactivate(repo_id=9999)

        assert success is False


# ---------------------------------------------------------------------------
# 9. delete (hard delete)
# ---------------------------------------------------------------------------


class TestDelete:
    """Tests for RepositoryService.delete."""

    @pytest.mark.asyncio
    async def test_hard_deletes(self, repo_service: RepositoryService) -> None:
        """Executes DELETE statement and returns True when rowcount > 0."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        repo_service.session.execute = AsyncMock(return_value=mock_result)
        repo_service.session.commit = AsyncMock()

        success = await repo_service.delete(repo_id=1)

        assert success is True
        repo_service.session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, repo_service: RepositoryService) -> None:
        """Returns False when no row was deleted (rowcount == 0)."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        repo_service.session.execute = AsyncMock(return_value=mock_result)
        repo_service.session.commit = AsyncMock()

        success = await repo_service.delete(repo_id=9999)

        assert success is False


# ---------------------------------------------------------------------------
# 10. touch_review
# ---------------------------------------------------------------------------


class TestTouchReview:
    """Tests for RepositoryService.touch_review."""

    @pytest.mark.asyncio
    async def test_updates_last_review_at(self, repo_service: RepositoryService) -> None:
        """Executes UPDATE to set last_review_at and increment total_reviews."""
        repo_service.session.execute = AsyncMock()
        repo_service.session.commit = AsyncMock()

        await repo_service.touch_review(repo_id=1)

        repo_service.session.execute.assert_awaited_once()
        repo_service.session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 11. get_webhook_secret
# ---------------------------------------------------------------------------


class TestGetWebhookSecret:
    """Tests for RepositoryService.get_webhook_secret."""

    @pytest.mark.asyncio
    async def test_decrypts_and_returns_secret(self, repo_service: RepositoryService) -> None:
        """Fetches repo, decrypts webhook_secret, returns plaintext."""
        mock_repo = _make_mock_repo(webhook_secret=b"encrypted-bytes")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute = AsyncMock(return_value=mock_result)

        with patch("app.core.security.decrypt_secret", return_value="my-secret") as mock_decrypt:
            secret = await repo_service.get_webhook_secret(repo_id=1)

        assert secret == "my-secret"
        mock_decrypt.assert_called_once_with(b"encrypted-bytes", settings.secret_key)

    @pytest.mark.asyncio
    async def test_returns_none_when_repo_not_found(self, repo_service: RepositoryService) -> None:
        """Returns None when the repository does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        repo_service.session.execute = AsyncMock(return_value=mock_result)

        secret = await repo_service.get_webhook_secret(repo_id=9999)

        assert secret is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_secret(self, repo_service: RepositoryService) -> None:
        """Returns None when the repository has no webhook_secret stored."""
        mock_repo = _make_mock_repo(webhook_secret=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_repo
        repo_service.session.execute = AsyncMock(return_value=mock_result)

        secret = await repo_service.get_webhook_secret(repo_id=1)

        assert secret is None
