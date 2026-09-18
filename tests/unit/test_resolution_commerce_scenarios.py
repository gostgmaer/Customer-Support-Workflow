"""app.agents.resolution's Phase 8.3 commerce scenarios: partial refunds,
subscription plan changes, shipping address changes, and payment retries -
each exercised directly against a real DB session (mirrors
tests/unit/test_resolution_storefront.py's pattern), not through the full
HTTP/LangGraph stack, since these are internal-resolver-only concerns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Order, Payment
from app.tools.base import ToolContext

pytestmark = pytest.mark.asyncio


async def _ctx(db_session, customer_id: str, workflow_run_id: str) -> ToolContext:
    return ToolContext(
        session=db_session,
        requesting_customer_id=customer_id,
        workflow_run_id=workflow_run_id,
        tenant_id=DEFAULT_TENANT_ID,
    )


async def _add_order(db_session, customer_id: str, *, status: str, total_amount: float = 100.0) -> str:
    # seeded_customer's own order is placed "now - 1 day" - placed_at
    # here must sort strictly more recent than that so
    # _handle_order_lookup's "latest order" query picks THIS one up,
    # not the fixture's.
    order_id = f"order_{uuid.uuid4().hex[:8]}"
    db_session.add(
        Order(
            id=order_id,
            customer_id=customer_id,
            status=status,
            total_amount=total_amount,
            currency="USD",
            product_name="Test Product",
            placed_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.flush()
    await db_session.commit()
    return order_id


# --- 8.3a: partial refunds ---


async def test_resolve_refund_extracts_partial_amount_from_message(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_refund

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_refund(
        ctx,
        customer_id,
        confirmed=False,
        conversation_id="conv_1",
        message_id="m1",
        message="I'd like a $20 refund please.",
        history=[],
    )

    assert outcome.pending_confirmation is True
    assert any("20" in fact and "USD" in fact for fact in outcome.facts)


async def test_resolve_refund_amount_survives_the_confirm_turn(
    db_session, seeded_customer, seeded_workflow_run
):
    """The customer's 'yes' reply carries no amount at all - the
    previously-stated partial amount must be recovered from history, not
    silently replaced with a full refund."""
    from app.agents.resolution import resolve_refund

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    history = [
        {"role": "user", "content": "I'd like a $20 refund please."},
        {"role": "assistant", "content": "Please confirm you would like a refund of 20.0 USD."},
    ]

    outcome = await resolve_refund(
        ctx,
        customer_id,
        confirmed=True,
        conversation_id=seeded_workflow_run["conversation_id"],
        message_id="m2",
        message="yes",
        history=history,
    )

    assert outcome.awaiting_approval is True
    assert any("20.0" in fact for fact in outcome.facts)


async def test_resolve_refund_clamps_amount_above_order_total(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_refund

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    # seeded_customer's order total is 99.99 - a stated $500 must clamp
    # down, never request more than the order is worth.
    outcome = await resolve_refund(
        ctx,
        customer_id,
        confirmed=False,
        conversation_id="conv_1",
        message_id="m1",
        message="I'd like a $500 refund please.",
        history=[],
    )

    assert any("99.99" in fact for fact in outcome.facts)


# --- 8.3b: subscription plan changes ---


async def test_resolve_subscription_change_requires_named_plan(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_subscription_change

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_subscription_change(
        ctx, customer_id, message="I want to change my plan", confirmed=False, history=[]
    )

    assert outcome.escalation_reason is not None


async def test_resolve_subscription_change_already_on_target_plan(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_subscription_change

    # seeded_customer's subscription plan is "Pro".
    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_subscription_change(
        ctx,
        customer_id,
        message="Please upgrade my subscription to the Pro plan",
        confirmed=False,
        history=[],
    )

    assert any("already" in fact.lower() for fact in outcome.facts)


async def test_resolve_subscription_change_plan_survives_the_confirm_turn(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_subscription_change

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    history = [
        {"role": "user", "content": "Please upgrade my subscription to the Enterprise plan."},
        {"role": "assistant", "content": "Please confirm you would like to switch to Enterprise."},
    ]

    outcome = await resolve_subscription_change(
        ctx, customer_id, message="yes", confirmed=True, history=history
    )

    assert any("Enterprise" in fact for fact in outcome.facts)
    assert any(call["args"].get("new_plan") == "Enterprise" for call in outcome.tool_calls)


# --- 8.3c: address changes (internal resolver always escalates) ---


async def test_resolve_address_change_on_changeable_order_escalates(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_address_change

    customer_id = seeded_customer["customer_id"]
    await _add_order(db_session, customer_id, status="processing")
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_address_change(ctx, customer_id)

    assert outcome.escalation_reason is not None


async def test_resolve_address_change_on_shipped_order_reports_it_deterministically(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_address_change

    customer_id = seeded_customer["customer_id"]
    await _add_order(db_session, customer_id, status="shipped")
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_address_change(ctx, customer_id)

    # No escalation needed here - this is a deterministic, immediate answer.
    assert outcome.escalation_reason is None
    assert any("shipped" in fact for fact in outcome.facts)


# --- 8.3d: payment retry ---


async def test_resolve_payment_retry_already_succeeded_reports_no_op(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_payment_retry

    # seeded_customer's payment is already "succeeded".
    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_payment_retry(ctx, customer_id, confirmed=True)

    assert any("not retried" in fact.lower() for fact in outcome.facts)


async def test_resolve_payment_retry_succeeds_for_a_failed_payment(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_payment_retry

    customer_id = seeded_customer["customer_id"]
    order_id = await _add_order(db_session, customer_id, status="processing")
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="failed", amount=42.0))
    await db_session.commit()
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_payment_retry(ctx, customer_id, confirmed=True)

    assert any("retried" in fact.lower() and "succeeded" in fact.lower() for fact in outcome.facts)


async def test_resolve_payment_retry_asks_for_confirmation_first(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_payment_retry

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_payment_retry(ctx, customer_id, confirmed=False)

    assert outcome.pending_confirmation is True
