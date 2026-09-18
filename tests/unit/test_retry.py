import pytest

from app.domain.exceptions import AuthorizationError, ToolError
from app.observability.retry import with_retry


@pytest.mark.asyncio
async def test_retries_transient_errors_until_success():
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ToolError("transient failure")
        return "ok"

    result = await with_retry(flaky, max_attempts=5)
    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_does_not_retry_non_retryable_errors():
    attempts = {"count": 0}

    async def always_fails():
        attempts["count"] += 1
        raise AuthorizationError("not allowed")

    with pytest.raises(AuthorizationError):
        await with_retry(always_fails, max_attempts=5)
    assert attempts["count"] == 1
