"""Idempotency service (spec §20).

key = f"{conversation_id}:{action}:{request_id}". First caller executes and
stores the result; a repeated call with the same key returns the stored
result instead of re-running the (potentially financial) action.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import IdempotencyKey

T = TypeVar("T")


def build_idempotency_key(conversation_id: str, action: str, request_id: str) -> str:
    return f"{conversation_id}:{action}:{request_id}"


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_completed(self, key: str) -> dict | None:
        record = await self._session.get(IdempotencyKey, key)
        if record is not None and record.status == "completed":
            return record.response
        return None

    async def run_once(
        self, key: str, action: str, fn: Callable[[], Awaitable[dict]]
    ) -> tuple[dict, bool]:
        """Returns (response, was_replayed)."""
        existing = await self._session.get(IdempotencyKey, key)
        if existing is not None and existing.status == "completed":
            return existing.response, True

        if existing is None:
            existing = IdempotencyKey(key=key, action=action, status="in_progress", response={})
            self._session.add(existing)
            await self._session.flush()

        result = await fn()
        existing.status = "completed"
        existing.response = result
        await self._session.flush()
        return result, False
