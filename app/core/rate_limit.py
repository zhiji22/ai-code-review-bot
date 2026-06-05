"""
Rate limiting via Redis sorted-set sliding window.

Per DESIGN.md §7.5: Sliding window algorithm.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, status

from app.core.redis import get_redis


async def check_rate_limit(
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> bool:
    """Check rate limit using sliding window algorithm.

    Uses Redis sorted sets to track requests within the time window.

    Args:
        key: Redis key for the rate limit bucket (e.g., rate:user:{user_id}).
        limit: Maximum requests allowed in the window.
        window_seconds: Window size in seconds (default 60).

    Returns:
        True if within limit.

    Raises:
        HTTPException 429 if rate limit exceeded.
    """
    redis = get_redis()
    now = time.time()
    window_start = now - window_seconds

    pipe = redis.pipeline()
    # Remove expired entries
    pipe.zremrangebyscore(key, 0, window_start)
    # Count current entries
    pipe.zcard(key)
    # Add current request
    pipe.zadd(key, {str(now): now})
    # Set expiry on the key
    pipe.expire(key, window_seconds + 10)

    results = await pipe.execute()
    current_count = results[1]

    if current_count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {current_count}/{limit} per {window_seconds}s",
            headers={
                "Retry-After": str(window_seconds),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    return True


async def get_rate_limit_info(
    key: str,
    limit: int,
    window_seconds: int = 60,
) -> dict[str, int]:
    """Get current rate limit status without incrementing.

    Args:
        key: Redis key.
        limit: Max requests.
        window_seconds: Window size.

    Returns:
        Dict with limit, remaining, reset_at.
    """
    redis = get_redis()
    now = time.time()
    window_start = now - window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)

    results = await pipe.execute()
    current = results[1]
    remaining = max(0, limit - current)

    return {
        "limit": limit,
        "remaining": remaining,
        "reset_at": int(now + window_seconds),
    }
