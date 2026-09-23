"""spec: Phase 15 - real aggregation queries over existing tables. Median
resolution time is computed in Python (statistics.median) rather than a
DB-side percentile function - this app supports both SQLite (dev/tests) and
Postgres (app.repositories.vector_store's own dual-backend precedent), and
there is no portable median expression across both; at this app's real
small-corpus scale (see Phase 11's own scale justification), fetching the
handful of resolved tickets in a reporting window and computing in Python
is the right proportionate choice, not a shortcut."""

from __future__ import annotations

import statistics
from datetime import datetime

from sqlalchemy import func, select

from app.domain.models.ticket import SupportTicket
from app.domain.models.workflow import WorkflowRun
from app.repositories.base import TenantScopedRepository


class AnalyticsRepository(TenantScopedRepository):
    async def ticket_counts_by_status(self, *, since: datetime, until: datetime) -> dict[str, int]:
        stmt = (
            self._scope(select(SupportTicket.status, func.count(SupportTicket.id)), SupportTicket)
            .where(SupportTicket.created_at >= since, SupportTicket.created_at < until)
            .group_by(SupportTicket.status)
        )
        result = await self.session.execute(stmt)
        return {status: count for status, count in result.all()}

    async def resolution_durations_minutes(self, *, since: datetime, until: datetime) -> list[float]:
        stmt = self._scope(
            select(SupportTicket.created_at, SupportTicket.resolved_at), SupportTicket
        ).where(
            SupportTicket.created_at >= since,
            SupportTicket.created_at < until,
            SupportTicket.resolved_at.is_not(None),
        )
        result = await self.session.execute(stmt)
        return [(resolved - created).total_seconds() / 60.0 for created, resolved in result.all()]

    async def sla_breach_count(self, *, since: datetime, until: datetime, now: datetime) -> int:
        """A ticket is breached if it's still unresolved past resolution_due_at,
        or it WAS resolved but after resolution_due_at. Computed on-demand -
        no scheduler exists anywhere in this codebase to detect this
        proactively (a deliberate, repeated constraint)."""
        stmt = self._scope(
            select(func.count(SupportTicket.id)), SupportTicket
        ).where(
            SupportTicket.created_at >= since,
            SupportTicket.created_at < until,
            SupportTicket.resolution_due_at.is_not(None),
            (
                (SupportTicket.resolved_at.is_(None) & (SupportTicket.resolution_due_at < now))
                | (
                    SupportTicket.resolved_at.is_not(None)
                    & (SupportTicket.resolved_at > SupportTicket.resolution_due_at)
                )
            ),
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def tickets_by_day(self, *, since: datetime, until: datetime) -> dict[str, int]:
        stmt = self._scope(select(SupportTicket.created_at), SupportTicket).where(
            SupportTicket.created_at >= since, SupportTicket.created_at < until
        )
        result = await self.session.execute(stmt)
        buckets: dict[str, int] = {}
        for (created_at,) in result.all():
            key = created_at.date().isoformat()
            buckets[key] = buckets.get(key, 0) + 1
        return buckets

    async def tickets_by_intent(self, *, since: datetime, until: datetime) -> dict[str, int]:
        stmt = (
            self._scope(select(SupportTicket.intent, func.count(SupportTicket.id)), SupportTicket)
            .where(SupportTicket.created_at >= since, SupportTicket.created_at < until)
            .group_by(SupportTicket.intent)
        )
        result = await self.session.execute(stmt)
        return dict(result.tuples().all())

    async def tickets_by_priority(self, *, since: datetime, until: datetime) -> dict[str, int]:
        stmt = (
            self._scope(select(SupportTicket.priority, func.count(SupportTicket.id)), SupportTicket)
            .where(SupportTicket.created_at >= since, SupportTicket.created_at < until)
            .group_by(SupportTicket.priority)
        )
        result = await self.session.execute(stmt)
        return dict(result.tuples().all())

    async def agent_activity(self, *, since: datetime, until: datetime) -> dict[str, dict[str, int]]:
        stmt = (
            self._scope(
                select(SupportTicket.approved_by, SupportTicket.status, func.count(SupportTicket.id)),
                SupportTicket,
            )
            .where(
                SupportTicket.created_at >= since,
                SupportTicket.created_at < until,
                SupportTicket.approved_by.is_not(None),
                SupportTicket.status.in_(("resolved", "rejected")),
            )
            .group_by(SupportTicket.approved_by, SupportTicket.status)
        )
        result = await self.session.execute(stmt)
        activity: dict[str, dict[str, int]] = {}
        for staff_id, status, count in result.all():
            entry = activity.setdefault(staff_id, {"resolved": 0, "rejected": 0})
            entry[status] = count
        return activity

    async def workflow_run_counts(self, *, since: datetime, until: datetime) -> tuple[int, int]:
        """Returns (total_runs, escalated_runs) - the honest denominator for
        an escalation rate.

        `WorkflowRun.requires_human` is deliberately NOT used here: it's a
        current-state field, not a historical one - app.workflow.nodes.save_outcome
        overwrites it to False the moment an escalated run's ticket is later
        approved and completes successfully (verified directly, not assumed -
        this was caught by a failing test during this phase's own
        implementation). A run that has an associated SupportTicket AT ALL is
        the reliable historical signal instead: a ticket is only ever created
        when a run required escalation at some point (see
        app.workflow.runner.run_workflow / app.workflow.nodes.save_outcome),
        regardless of what happens to it afterward."""
        total_stmt = self._scope(select(func.count(WorkflowRun.id)), WorkflowRun).where(
            WorkflowRun.created_at >= since, WorkflowRun.created_at < until
        )
        escalated_stmt = self._scope(
            select(func.count(func.distinct(WorkflowRun.id))), WorkflowRun
        ).where(
            WorkflowRun.created_at >= since,
            WorkflowRun.created_at < until,
            WorkflowRun.id.in_(
                select(SupportTicket.workflow_run_id).where(
                    SupportTicket.tenant_id == self.tenant_id,
                    SupportTicket.workflow_run_id.is_not(None),
                )
            ),
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        escalated = (await self.session.execute(escalated_stmt)).scalar_one()
        return int(total), int(escalated)


def median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def average_or_none(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
