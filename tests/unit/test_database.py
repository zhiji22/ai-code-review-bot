"""Unit tests for database connection management."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# We need to reset module-level singletons between tests.
# The database module stores _engine and _session_factory as globals.
def _reset_database_module() -> None:
    """Reset module-level engine and session factory singletons."""
    import app.core.database as db_mod

    db_mod._engine = None
    db_mod._session_factory = None


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Ensure singletons are reset before each test."""
    _reset_database_module()
    yield
    _reset_database_module()


class TestGetEngine:
    """Tests for get_engine function."""

    def test_get_engine_creates_engine(self) -> None:
        """When no engine exists, creates one from settings."""
        from app.core.database import get_engine

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        mock_settings.db_pool_size = 5
        mock_settings.db_max_overflow = 10
        mock_settings.db_echo = False
        mock_settings.db_use_null_pool = False

        with patch("app.core.database.get_settings", return_value=mock_settings):
            with patch("app.core.database.create_async_engine") as mock_create:
                mock_engine = MagicMock()
                mock_create.return_value = mock_engine

                engine = get_engine()

        assert engine is mock_engine
        mock_create.assert_called_once_with(
            "postgresql+asyncpg://user:pass@localhost:5432/testdb",
            pool_size=5,
            max_overflow=10,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

    def test_get_engine_singleton(self) -> None:
        """Calling get_engine twice returns the same instance."""
        from app.core.database import get_engine

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
        mock_settings.db_pool_size = 5
        mock_settings.db_max_overflow = 10
        mock_settings.db_echo = False
        mock_settings.db_use_null_pool = False

        with patch("app.core.database.get_settings", return_value=mock_settings):
            with patch("app.core.database.create_async_engine") as mock_create:
                mock_engine = MagicMock()
                mock_create.return_value = mock_engine

                engine1 = get_engine()
                engine2 = get_engine()

        assert engine1 is engine2
        # create_async_engine should only be called once
        assert mock_create.call_count == 1

    def test_get_engine_uses_settings_values(self) -> None:
        """Engine is created with the exact values from settings."""
        from app.core.database import get_engine

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql+asyncpg://admin:secret@db:5432/prod"
        mock_settings.db_pool_size = 20
        mock_settings.db_max_overflow = 30
        mock_settings.db_echo = True
        mock_settings.db_use_null_pool = False

        with patch("app.core.database.get_settings", return_value=mock_settings):
            with patch("app.core.database.create_async_engine") as mock_create:
                mock_create.return_value = MagicMock()
                get_engine()

        call_kwargs = mock_create.call_args
        assert call_kwargs[0][0] == "postgresql+asyncpg://admin:secret@db:5432/prod"
        assert call_kwargs[1]["pool_size"] == 20
        assert call_kwargs[1]["max_overflow"] == 30
        assert call_kwargs[1]["echo"] is True
        assert call_kwargs[1]["pool_pre_ping"] is True
        assert call_kwargs[1]["pool_recycle"] == 3600


class TestGetEngineNullPool:
    """开启 db_use_null_pool 时必须使用 NullPool。

    回归测试:Celery 每个任务都新建一个 asyncio 事件循环,任务结束即关闭;
    asyncpg 连接绑定在创建它的循环上,下一个任务(新循环)复用池中连接会抛
    ``RuntimeError: ... Future ... attached to a different loop``。NullPool
    每次用完即弃连接,所以没有任何连接能跨循环存活。
    backend(uvicorn)跑在单一长生命周期循环上,继续使用连接池。
    """

    def test_null_pool_used_when_flag_set(self) -> None:
        from app.core.database import get_engine
        from sqlalchemy.pool import NullPool

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql+asyncpg://u:p@localhost:5432/db"
        mock_settings.db_echo = False
        mock_settings.db_use_null_pool = True

        with patch("app.core.database.get_settings", return_value=mock_settings):
            with patch("app.core.database.create_async_engine") as mock_create:
                mock_create.return_value = MagicMock()
                get_engine()

        kwargs = mock_create.call_args[1]
        assert kwargs.get("poolclass") is NullPool
        # pool_size 等 pre-ping/池大小参数对 NullPool 无意义,不应传入
        # (SQLAlchemy 会忽略,这里断言只是为了明确意图)。
        assert "pool_size" not in kwargs
        assert "max_overflow" not in kwargs
        assert "pool_pre_ping" not in kwargs
        assert "pool_recycle" not in kwargs

    def test_queue_pool_used_when_flag_unset(self) -> None:
        from app.core.database import get_engine

        mock_settings = MagicMock()
        mock_settings.database_url = "postgresql+asyncpg://u:p@localhost:5432/db"
        mock_settings.db_pool_size = 5
        mock_settings.db_max_overflow = 10
        mock_settings.db_echo = False
        mock_settings.db_use_null_pool = False

        with patch("app.core.database.get_settings", return_value=mock_settings):
            with patch("app.core.database.create_async_engine") as mock_create:
                mock_create.return_value = MagicMock()
                get_engine()

        kwargs = mock_create.call_args[1]
        assert "poolclass" not in kwargs
        assert kwargs["pool_size"] == 5
        assert kwargs["pool_pre_ping"] is True


class TestGetSessionFactory:
    """Tests for get_session_factory function."""

    def test_get_session_factory(self) -> None:
        """Creates session factory from engine."""
        from app.core.database import get_session_factory

        mock_engine = MagicMock()

        with patch("app.core.database.get_engine", return_value=mock_engine):
            with patch("app.core.database.async_sessionmaker") as mock_maker:
                mock_factory = MagicMock()
                mock_maker.return_value = mock_factory

                factory = get_session_factory()

        assert factory is mock_factory
        mock_maker.assert_called_once_with(
            mock_engine,
            class_=mock_maker.call_args[1]["class_"],
            expire_on_commit=False,
        )

    def test_get_session_factory_singleton(self) -> None:
        """Calling get_session_factory twice returns the same instance."""
        from app.core.database import get_session_factory

        mock_engine = MagicMock()

        with patch("app.core.database.get_engine", return_value=mock_engine):
            with patch("app.core.database.async_sessionmaker") as mock_maker:
                mock_factory = MagicMock()
                mock_maker.return_value = mock_factory

                factory1 = get_session_factory()
                factory2 = get_session_factory()

        assert factory1 is factory2
        assert mock_maker.call_count == 1


class TestGetDbSession:
    """Tests for get_db_session async context manager."""

    @pytest.mark.asyncio
    async def test_get_db_session_commit(self) -> None:
        """Successful operation commits the session."""
        from app.core.database import get_db_session

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        # The factory() call returns an async context manager
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session_cm

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            async with get_db_session() as session:
                assert session is mock_session

        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_db_session_rollback_on_error(self) -> None:
        """Exception during session triggers rollback and re-raises."""
        from app.core.database import get_db_session

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session_cm

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            with pytest.raises(ValueError, match="test error"):
                async with get_db_session():
                    raise ValueError("test error")

        mock_session.rollback.assert_awaited_once()
        # commit should NOT be called when an exception occurs
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_db_session_commit_not_called_before_yield(self) -> None:
        """Commit happens after the context block, not before."""
        from app.core.database import get_db_session

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session_cm

        commit_called_during = False

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            async with get_db_session():
                commit_called_during = mock_session.commit.called

        assert commit_called_during is False
        mock_session.commit.assert_awaited_once()


class TestGetDb:
    """Tests for get_db FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_get_db_yields_session(self) -> None:
        """FastAPI dependency yields a session and closes it afterward."""
        from app.core.database import get_db

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session_cm

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            gen = get_db()
            session = await gen.__anext__()

        assert session is mock_session

        # Exhaust the generator to trigger cleanup
        with contextlib.suppress(StopAsyncIteration):
            await gen.__anext__()

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_db_closes_session_on_exception(self) -> None:
        """Session is closed even when an exception occurs in the consumer."""
        from app.core.database import get_db

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session_cm

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            gen = get_db()
            session = await gen.__anext__()
            assert session is mock_session

            # Simulate consumer throwing an exception
            with contextlib.suppress(RuntimeError):
                await gen.athrow(RuntimeError("consumer error"))

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_db_no_commit(self) -> None:
        """get_db dependency does NOT auto-commit (unlike get_db_session)."""
        from app.core.database import get_db

        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_session_cm

        with patch("app.core.database.get_session_factory", return_value=mock_factory):
            gen = get_db()
            await gen.__anext__()
            with contextlib.suppress(StopAsyncIteration):
                await gen.__anext__()

        # get_db should NOT call commit — it only closes
        mock_session.commit.assert_not_awaited()
        mock_session.close.assert_awaited_once()
