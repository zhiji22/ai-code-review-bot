"""
Redis client management.

Per DESIGN.md §5/§7.4/§7.5: Redis for caching, idempotency, rate limiting, Celery broker.
"""

from __future__ import annotations

import asyncio

import redis.asyncio as redis

from app.core.config import get_settings

_redis_client: redis.Redis | None = None
# Event loop the cached client was created on. redis-py 的底层连接绑定在创建它的
# 事件循环上;Celery worker/beat 每个任务都新建并关闭一个循环,跨循环复用同一个
# 客户端会抛 ``RuntimeError: Event loop is closed``(见 cache_read_error 日志)。
# 检测到当前运行循环与缓存时不同时,丢弃旧客户端并重建。
_redis_client_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> redis.Redis:
    """Get or create a Redis client bound to the current event loop.

    Unlike the DB engine (which uses NullPool to dodge the cross-loop problem),
    redis-py has no equivalent, so we track the loop a client was created on and
    recreate it when the running loop changes. This keeps the singleton fast on
    a long-lived loop (uvicorn backend) while staying safe across per-task loops
    (Celery worker/beat).
    """
    global _redis_client, _redis_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside any loop — rare; fall back to whatever is cached.
        current_loop = None

    if _redis_client is None or _redis_client_loop is not current_loop:
        settings = get_settings()
        _redis_client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        _redis_client_loop = current_loop
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection on shutdown."""
    global _redis_client, _redis_client_loop
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        _redis_client_loop = None
