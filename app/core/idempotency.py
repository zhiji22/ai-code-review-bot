"""
Idempotency middleware using Redis SETNX.

Per DESIGN.md §7.4: Prevent duplicate webhook processing.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.redis import get_redis


async def check_idempotency(key: str, ttl: int = 3600) -> bool:
    """Check if this request has already been processed.

    Uses Redis SET NX (set-if-not-exists) for atomic idempotency check.

    Args:
        key: Idempotency key (e.g., webhook:pr:{repo}:{pr_num}:{commit_sha}).
        ttl: Time-to-live in seconds (default 3600 = 1 hour).

    Returns:
        True if this is a new request (proceed).
        False if duplicate (should return 409).

    Raises:
        HTTPException 409 if duplicate.
    """
    redis = get_redis()
    result = await redis.set(key, "1", nx=True, ex=ttl)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate webhook — already processing this commit",
        )
    return True


async def release_idempotency(key: str) -> None:
    """Release the idempotency lock (on failure, to allow retry).

    Args:
        key: The idempotency key to release.
    """
    redis = get_redis()
    await redis.delete(key)


def build_webhook_idempotency_key(
    repo_full_name: str,
    pr_number: int,
    commit_sha: str,
) -> str:
    """Build the Redis idempotency key for a PR webhook.

    Args:
        repo_full_name: e.g. "owner/repo".
        pr_number: Pull request number.
        commit_sha: The head commit SHA.

    Returns:
        Redis key string.
    """
    return f"webhook:pr:{repo_full_name}:{pr_number}:{commit_sha}"
