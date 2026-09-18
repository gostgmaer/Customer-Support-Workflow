import pytest

from app.domain.exceptions import RateLimitError
from app.security.rate_limit import InMemoryRateLimiter


@pytest.mark.asyncio
async def test_allows_requests_within_limit():
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.check("key1", limit=3, window_seconds=60)


@pytest.mark.asyncio
async def test_rejects_requests_over_limit():
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.check("key2", limit=3, window_seconds=60)
    with pytest.raises(RateLimitError):
        await limiter.check("key2", limit=3, window_seconds=60)


@pytest.mark.asyncio
async def test_different_keys_have_independent_limits():
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        await limiter.check("key3", limit=3, window_seconds=60)
    # A different key must not be affected by key3's usage.
    await limiter.check("key4", limit=3, window_seconds=60)
