"""spec: Phase 15 - CSAT. app.domain.models.feedback.Feedback existed since
the original schema (migration 0001) but had zero repository/route/usage
anywhere until now - this makes it a real, working feature."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from app.domain.models.feedback import Feedback
from app.repositories.base import TenantScopedRepository


class FeedbackRepository(TenantScopedRepository):
    async def create(
        self, *, conversation_id: str, rating: int, comment: str = "", resolved: bool = True
    ) -> Feedback:
        feedback = Feedback(
            tenant_id=self.tenant_id,
            conversation_id=conversation_id,
            rating=rating,
            comment=comment,
            resolved=resolved,
        )
        self.session.add(feedback)
        await self.session.flush()
        return feedback

    async def get_for_conversation(self, conversation_id: str) -> Feedback | None:
        stmt = self._scope(
            select(Feedback).where(Feedback.conversation_id == conversation_id), Feedback
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def average_rating(
        self, *, since: datetime | None = None, until: datetime | None = None
    ) -> tuple[float | None, int]:
        """Returns (average_rating, count) for the tenant, optionally
        windowed by `created_at`. average_rating is None when count is 0 -
        never fabricated as 0.0, which would misleadingly read as "worst
        possible score" rather than "no data"."""
        stmt = self._scope(select(func.avg(Feedback.rating), func.count(Feedback.id)), Feedback)
        if since is not None:
            stmt = stmt.where(Feedback.created_at >= since)
        if until is not None:
            stmt = stmt.where(Feedback.created_at < until)
        result = await self.session.execute(stmt)
        avg_rating, count = result.one()
        return (float(avg_rating) if avg_rating is not None else None, int(count))
