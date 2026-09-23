"""spec: Phase 15 - staff-facing analytics over real support/workflow/CSAT
data already in this app's schema. See app.repositories.analytics for the
honesty note on why median resolution time is computed in Python rather
than a DB-side percentile expression."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.analytics import (
    AgentActivity,
    AnalyticsSummary,
    IntentCount,
    PriorityCount,
    TicketVolumePoint,
)
from app.db.base import utcnow
from app.db.session import get_db
from app.repositories.analytics import AnalyticsRepository, average_or_none, median_or_none
from app.repositories.feedback import FeedbackRepository
from app.security.auth import require_staff_role

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

RequireStaff = Depends(require_staff_role())


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireStaff,
) -> dict:
    _staff_id, _role, tenant_id = staff
    now = utcnow()
    since = now - timedelta(days=days)

    repo = AnalyticsRepository(session, tenant_id)
    status_counts = await repo.ticket_counts_by_status(since=since, until=now)
    durations = await repo.resolution_durations_minutes(since=since, until=now)
    breached = await repo.sla_breach_count(since=since, until=now, now=now)
    by_day = await repo.tickets_by_day(since=since, until=now)
    by_intent = await repo.tickets_by_intent(since=since, until=now)
    by_priority = await repo.tickets_by_priority(since=since, until=now)
    activity = await repo.agent_activity(since=since, until=now)
    total_runs, escalated_runs = await repo.workflow_run_counts(since=since, until=now)

    total_tickets = sum(status_counts.values())
    csat_avg, csat_count = await FeedbackRepository(session, tenant_id).average_rating(
        since=since, until=now
    )

    return {
        "period_start": since.isoformat(),
        "period_end": now.isoformat(),
        "total_tickets": total_tickets,
        "resolved_tickets": status_counts.get("resolved", 0),
        "rejected_tickets": status_counts.get("rejected", 0),
        "open_tickets": status_counts.get("open", 0),
        "avg_resolution_minutes": average_or_none(durations),
        "median_resolution_minutes": median_or_none(durations),
        "sla_breached_count": breached,
        "sla_breach_rate": (breached / total_tickets) if total_tickets else None,
        "total_workflow_runs": total_runs,
        "escalated_workflow_runs": escalated_runs,
        "escalation_rate": (escalated_runs / total_runs) if total_runs else None,
        "csat_average": csat_avg,
        "csat_count": csat_count,
        "ticket_volume_by_day": [
            TicketVolumePoint(date=day, count=count) for day, count in sorted(by_day.items())
        ],
        "tickets_by_intent": [
            IntentCount(intent=intent, count=count) for intent, count in sorted(by_intent.items())
        ],
        "tickets_by_priority": [
            PriorityCount(priority=priority, count=count)
            for priority, count in sorted(by_priority.items())
        ],
        "agent_activity": [
            AgentActivity(
                staff_id=staff_id,
                approved_count=counts.get("resolved", 0),
                rejected_count=counts.get("rejected", 0),
            )
            for staff_id, counts in sorted(activity.items())
        ],
    }
