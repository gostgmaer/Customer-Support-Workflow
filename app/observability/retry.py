"""Retry policy (spec §19): exponential backoff for transient failures only.

Non-retryable errors (auth, validation, business-rule rejection, security)
must never be retried - they are re-raised immediately by
`retryable_operation` via each error's `.retryable` flag.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.domain.exceptions import SupportWorkflowError
from app.observability.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, SupportWorkflowError):
        return exc.retryable
    # Unknown exceptions (e.g. raw network errors) are treated as transient.
    return True


def _log_retry(retry_state) -> None:  # noqa: ANN001
    logger.warning(
        "retry_attempt",
        attempt=retry_state.attempt_number,
        wait=str(retry_state.next_action.sleep if retry_state.next_action else None),
    )


def build_retry_decorator(max_attempts: int | None = None):
    settings = get_settings()
    attempts = max_attempts or settings.retry_max_attempts
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception(_is_retryable),
        before_sleep=_log_retry,
        reraise=True,
    )


async def with_retry(fn: Callable[[], Awaitable[T]], *, max_attempts: int | None = None) -> T:
    """Run an async callable under the exponential-backoff retry policy."""
    decorated = build_retry_decorator(max_attempts)(fn)
    return await decorated()
