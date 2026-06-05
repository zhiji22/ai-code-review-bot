"""
Redis client management.

Per DESIGN.md §5/§7.4/§7.5: Redis for caching, idempotency, rate limiting, Celery broker.
"""

from __future__ import annotations

import redis.asyncio as redis

from app.core.config import get_settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Get or create the Redis client singleton."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
        )
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection on shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
