"""spec: Phase 15 - FeedbackRepository (CSAT) and AnalyticsRepository's SLA
breach detection, tested directly against the real DB session rather than
only through the full HTTP scenario tests (tests/workflow/test_scenarios.py
covers the end-to-end flow; this file covers repository-level edge cases
that are awkward to force through the real workflow)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import SupportTicket
from app.repositories.analytics import AnalyticsRepository
from app.repositories.feedback import FeedbackRepository


@pytest.mark.asyncio
async def test_average_rating_is_none_with_no_feedback(db_session):
    repo = FeedbackRepository(db_session, DEFAULT_TENANT_ID)
    avg, count = await repo.average_rating()
    assert avg is None
    assert count == 0


@pytest.mark.asyncio
async def test_average_rating_computes_real_average(db_session, seeded_workflow_run):
    # The repository itself doesn't enforce one-feedback-per-conversation
    # (that check lives in the route - see app.api.routes.support) so two
    # rows against the same real, FK-valid conversation is a fine way to
    # exercise the averaging math without seeding a second conversation.
    repo = FeedbackRepository(db_session, DEFAULT_TENANT_ID)
    await repo.create(conversation_id=seeded_workflow_run["conversation_id"], rating=5)
    await repo.create(conversation_id=seeded_workflow_run["conversation_id"], rating=3)
    await db_session.commit()

    avg, count = await repo.average_rating()
    assert count == 2
    assert avg == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_get_for_conversation_returns_none_when_absent(db_session, seeded_workflow_run):
    repo = FeedbackRepository(db_session, DEFAULT_TENANT_ID)
    result = await repo.get_for_conversation(seeded_workflow_run["conversation_id"])
    assert result is None


async def _make_ticket(
    db_session, *, customer_id: str, conversation_id: str, resolution_due_at, resolved_at
) -> SupportTicket:
    ticket = SupportTicket(
        tenant_id=DEFAULT_TENANT_ID,
        conversation_id=conversation_id,
        customer_id=customer_id,
        intent="REFUND",
        priority="HIGH",
        status="resolved" if resolved_at else "open",
        summary="test",
        customer_problem="test",
        reason_for_escalation="test",
        resolution_due_at=resolution_due_at,
        resolved_at=resolved_at,
    )
    db_session.add(ticket)
    await db_session.flush()
    return ticket


@pytest.mark.asyncio
async def test_sla_breach_count_flags_a_ticket_resolved_after_its_due_time(
    db_session, seeded_customer, seeded_workflow_run
):
    now = datetime.now(UTC)
    due = now - timedelta(hours=1)
    resolved_late = now  # resolved AFTER the due time - a real breach
    await _make_ticket(
        db_session,
        customer_id=seeded_customer["customer_id"],
        conversation_id=seeded_workflow_run["conversation_id"],
        resolution_due_at=due,
        resolved_at=resolved_late,
    )
    await db_session.commit()

    repo = AnalyticsRepository(db_session, DEFAULT_TENANT_ID)
    count = await repo.sla_breach_count(since=now - timedelta(days=1), until=now + timedelta(days=1), now=now)
    assert count == 1


@pytest.mark.asyncio
async def test_sla_breach_count_ignores_a_ticket_resolved_before_its_due_time(
    db_session, seeded_customer, seeded_workflow_run
):
    now = datetime.now(UTC)
    due = now + timedelta(hours=1)
    resolved_on_time = now  # resolved BEFORE the due time - not a breach
    await _make_ticket(
        db_session,
        customer_id=seeded_customer["customer_id"],
        conversation_id=seeded_workflow_run["conversation_id"],
        resolution_due_at=due,
        resolved_at=resolved_on_time,
    )
    await db_session.commit()

    repo = AnalyticsRepository(db_session, DEFAULT_TENANT_ID)
    count = await repo.sla_breach_count(since=now - timedelta(days=1), until=now + timedelta(days=1), now=now)
    assert count == 0


@pytest.mark.asyncio
async def test_sla_breach_count_flags_a_still_open_ticket_past_its_due_time(
    db_session, seeded_customer, seeded_workflow_run
):
    now = datetime.now(UTC)
    overdue = now - timedelta(hours=1)
    await _make_ticket(
        db_session,
        customer_id=seeded_customer["customer_id"],
        conversation_id=seeded_workflow_run["conversation_id"],
        resolution_due_at=overdue,
        resolved_at=None,
    )
    await db_session.commit()

    repo = AnalyticsRepository(db_session, DEFAULT_TENANT_ID)
    count = await repo.sla_breach_count(since=now - timedelta(days=1), until=now + timedelta(days=1), now=now)
    assert count == 1


@pytest.mark.asyncio
async def test_resolution_durations_minutes_only_includes_resolved_tickets(
    db_session, seeded_customer, seeded_workflow_run
):
    now = datetime.now(UTC)
    await _make_ticket(
        db_session,
        customer_id=seeded_customer["customer_id"],
        conversation_id=seeded_workflow_run["conversation_id"],
        resolution_due_at=now,
        resolved_at=None,
    )
    await db_session.commit()

    repo = AnalyticsRepository(db_session, DEFAULT_TENANT_ID)
    durations = await repo.resolution_durations_minutes(
        since=now - timedelta(days=1), until=now + timedelta(days=1)
    )
    assert durations == []
