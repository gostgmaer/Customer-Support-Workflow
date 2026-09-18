"""Rate limiting (spec §23).

Fixed-window counter keyed by caller identity (customer id / staff id).
`InMemoryRateLimiter` is the zero-setup default (correct for a single API
process); `RedisRateLimiter` is used automatically when `USE_REDIS=true` so
multiple API instances share one counter instead of each allowing the full
quota independently. Both implement the same `RateLimiter` protocol, so
nothing above this module needs to know which one is active - the same
repository-interface pattern used for the vector store and LLM provider.
"""

from __future__ import annotations

import time
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.exceptions import RateLimitError
from app.observability.logging import get_logger

logger = get_logger(__name__)


class RateLimiter(Protocol):
    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        """Raises RateLimitError if `key` has exceeded `limit` requests in
        the current `window_seconds`-second window; otherwise records this
        call and returns."""
        ...


class InMemoryRateLimiter:
    """Process-local fixed-window counter. Like `InMemoryVectorStore`, the
    counters are a class-level dict shared across instances within one
    process - correct for a single API instance, not for a fleet."""

    _windows: dict[str, tuple[int, int]] = {}  # key -> (window_start_epoch, count)

    @classmethod
    def reset(cls) -> None:
        cls._windows.clear()

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        stored_start, count = self._windows.get(key, (window_start, 0))

        if stored_start != window_start:
            count = 0
            stored_start = window_start

        count += 1
        self._windows[key] = (stored_start, count)

        if count > limit:
            raise RateLimitError(
                f"Rate limit exceeded: {limit} requests per {window_seconds}s",
                details={"key": key, "limit": limit, "window_seconds": window_seconds},
            )


class RedisRateLimiter:
    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as redis

        self._client = redis.from_url(redis_url, decode_responses=True)

    async def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = int(time.time())
        window_start = now - (now % window_seconds)
        redis_key = f"ratelimit:{key}:{window_start}"

        count = await self._client.incr(redis_key)
        if count == 1:
            await self._client.expire(redis_key, window_seconds)

        if count > limit:
            raise RateLimitError(
                f"Rate limit exceeded: {limit} requests per {window_seconds}s",
                details={"key": key, "limit": limit, "window_seconds": window_seconds},
            )


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = RedisRateLimiter(settings.redis_url) if settings.use_redis else InMemoryRateLimiter()
    return _limiter


async def enforce_rate_limit(
    key: str,
    *,
    limit: int | None = None,
    window_seconds: int | None = None,
    session: AsyncSession | None = None,
    tenant_id: str | None = None,
) -> None:
    """`session`+`tenant_id` (when `limit`/`window_seconds` aren't given
    explicitly) resolve this tenant's DB-overridden rate limit (spec §43,
    `app.config.dynamic_settings`) instead of the env-var default - used by
    `/support/messages`. Staff login has no tenant yet at this point (see
    docs/SECURITY.md), so it never passes these and stays on the env-var
    default."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    if (limit is None or window_seconds is None) and session is not None and tenant_id is not None:
        from app.config.dynamic_settings import get_effective_settings

        effective = await get_effective_settings(session, tenant_id)
        limit = limit if limit is not None else effective.rate_limit_per_window
        window_seconds = window_seconds if window_seconds is not None else effective.rate_limit_window_seconds

    await get_rate_limiter().check(
        key,
        limit=limit if limit is not None else settings.rate_limit_per_window,
        window_seconds=window_seconds if window_seconds is not None else settings.rate_limit_window_seconds,
    )
