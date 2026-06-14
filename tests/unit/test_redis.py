"""Unit tests for Redis client management — loop-aware singleton.

Celery worker/beat 每个任务都新建并关闭一个 asyncio 事件循环(`review_tasks.py`
里 ``loop = asyncio.new_event_loop()`` … ``loop.close()``)。redis 客户端若做成
全局单例且不感知循环,第一个任务的循环关闭后,下一个任务复用同一个客户端会抛
``RuntimeError: Event loop is closed``(``cache_read_error``)。这里回归测试:
同一个循环复用客户端,换了循环必须重建。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

# Each from_url() call must yield a DISTINCT client, otherwise a shared mock
# return value would make two real creations look identical and mask the bug.
_NEW_CLIENT_EACH_CALL = lambda *args, **kwargs: object()  # noqa: E731


def _reset_redis_module() -> None:
    """Reset module-level singleton + loop tracking between tests."""
    import app.core.redis as redis_mod

    redis_mod._redis_client = None
    # Attribute may not exist yet before the fix lands; assignment is safe.
    redis_mod._redis_client_loop = None  # type: ignore[attr-defined]


async def _call_get_redis() -> object:
    """Call the sync get_redis() from within a running loop."""
    from app.core.redis import get_redis

    return get_redis()


class TestRedisLoopAware:
    """get_redis() must recreate the client when the running loop changes."""

    def test_same_loop_reuses_client(self) -> None:
        _reset_redis_module()
        loop = asyncio.new_event_loop()
        try:
            with patch("app.core.redis.redis.Redis.from_url", side_effect=_NEW_CLIENT_EACH_CALL) as mock_from_url:
                c1 = loop.run_until_complete(_call_get_redis())
                c2 = loop.run_until_complete(_call_get_redis())
                assert c1 is c2
                assert mock_from_url.call_count == 1
        finally:
            loop.close()
            _reset_redis_module()

    def test_new_loop_recreates_client(self) -> None:
        """The core regression: a fresh loop (next Celery task) must get a fresh client."""
        _reset_redis_module()
        loop1 = asyncio.new_event_loop()
        loop2 = asyncio.new_event_loop()
        try:
            with patch("app.core.redis.redis.Redis.from_url", side_effect=_NEW_CLIENT_EACH_CALL) as mock_from_url:
                c1 = loop1.run_until_complete(_call_get_redis())
                # loop1 corresponds to a finished task; next task runs on loop2.
                c2 = loop2.run_until_complete(_call_get_redis())
                assert c1 is not c2
                assert mock_from_url.call_count == 2
        finally:
            loop1.close()
            loop2.close()
            _reset_redis_module()
