"""app.agents.resolution's Phase 13 scenarios: account/identity (profile
update, account unlock, merge escalation), billing extras (duplicate
charge, payment method redirect, gift card escalation), product
(bulk/wholesale escalation), and the lost-package discrepancy branch of
resolve_order_status. Exercised directly against a real DB session,
mirroring test_resolution_commerce_scenarios.py's pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Customer, Order, Payment
from app.tools.base import ToolContext

pytestmark = pytest.mark.asyncio


async def _ctx(db_session, customer_id: str, workflow_run_id: str) -> ToolContext:
    return ToolContext(
        session=db_session,
        requesting_customer_id=customer_id,
        workflow_run_id=workflow_run_id,
        tenant_id=DEFAULT_TENANT_ID,
    )


async def _add_order(db_session, customer_id: str, *, status: str = "delivered") -> str:
    order_id = f"order_{uuid.uuid4().hex[:8]}"
    db_session.add(
        Order(
            id=order_id,
            customer_id=customer_id,
            status=status,
            total_amount=100.0,
            currency="USD",
            product_name="Test Product",
            placed_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.flush()
    await db_session.commit()
    return order_id


# --- extract_profile_update_target ---


def test_extract_profile_update_target_finds_an_email():
    from app.agents.resolution import extract_profile_update_target

    target = extract_profile_update_target("Please change my email to newaddress@example.com")
    assert target == {"new_email": "newaddress@example.com"}


def test_extract_profile_update_target_finds_a_name():
    from app.agents.resolution import extract_profile_update_target

    target = extract_profile_update_target("Please update my name to Jordan Lee")
    assert target["new_full_name"] == "Jordan Lee"


def test_extract_profile_update_target_empty_when_nothing_stated():
    from app.agents.resolution import extract_profile_update_target

    assert extract_profile_update_target("I want to update my profile") == {}


# --- resolve_profile_update ---


async def test_resolve_profile_update_no_target_escalates(db_session, seeded_customer, seeded_workflow_run):
    from app.agents.resolution import resolve_profile_update

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_profile_update(ctx, customer_id, confirmed=False, profile_update_target=None)

    assert outcome.escalation_reason is not None
    assert outcome.awaiting_approval is False


async def test_resolve_profile_update_asks_for_confirmation_first(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_profile_update

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_profile_update(
        ctx, customer_id, confirmed=False, profile_update_target={"new_email": "new@example.com"}
    )

    assert outcome.pending_confirmation is True
    assert outcome.awaiting_approval is False


async def test_resolve_profile_update_target_survives_the_confirm_turn_via_conversation_metadata(
    db_session, seeded_customer, seeded_workflow_run
):
    """spec: Phase 13 live-testing bug - the confirmation reply carries no
    email at all (unlike a dollar amount, redact() strips it before it
    ever reaches history), so this must recover the target from
    Conversation.metadata_json, not history."""
    from app.agents.resolution import gather_resolution_facts

    customer_id = seeded_customer["customer_id"]
    conversation_id = seeded_workflow_run["conversation_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    first = await gather_resolution_facts(
        ctx, intent="PROFILE_UPDATE", customer_id=customer_id, conversation_id=conversation_id,
        message_id="m1", message="Please change my email to newmail@example.com", history=[],
        retrieved_documents=[],
        profile_update_target={"new_email": "newmail@example.com"},
    )
    assert first.pending_confirmation is True

    second = await gather_resolution_facts(
        ctx, intent="PROFILE_UPDATE", customer_id=customer_id, conversation_id=conversation_id,
        message_id="m2", message="Yes, please go ahead and update it.",
        history=[
            {"role": "user", "content": "Please change my email to <EMAIL_REDACTED>"},
            {"role": "assistant", "content": "Please confirm you would like to update your profile."},
        ],
        retrieved_documents=[], profile_update_target=None,
    )
    assert second.awaiting_approval is True
    assert second.pending_internal_call == {
        "tool": "update_customer_profile",
        "args": {"customer_id": customer_id, "new_email": "newmail@example.com"},
    }


async def test_resolve_profile_update_confirmed_proposes_but_does_not_apply(
    db_session, seeded_customer, seeded_workflow_run
):
    """The change must NOT take effect yet - only human_approval_gate's
    _execute_approved_internal_call applies it, after staff approval."""
    from app.agents.resolution import resolve_profile_update

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_profile_update(
        ctx, customer_id, confirmed=True, profile_update_target={"new_email": "new@example.com"}
    )

    assert outcome.awaiting_approval is True
    assert outcome.pending_internal_call == {
        "tool": "update_customer_profile",
        "args": {"customer_id": customer_id, "new_email": "new@example.com"},
    }
    result = await db_session.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one()
    assert customer.email != "new@example.com"


# --- resolve_account_access ---


async def test_resolve_account_access_merge_request_escalates(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_account_access

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_account_access(
        ctx, customer_id, confirmed=False, message="I have two accounts, can you merge them?"
    )

    assert outcome.escalation_reason is not None
    assert "merge" in outcome.escalation_reason.lower()


async def test_resolve_account_access_not_locked_defers_to_password_reset(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_account_access

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_account_access(ctx, customer_id, confirmed=False, message="I'm locked out")

    assert any("verification email" in fact.lower() for fact in outcome.facts)
    assert outcome.awaiting_approval is False


async def test_resolve_account_access_locked_asks_for_confirmation(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_account_access

    customer_id = seeded_customer["customer_id"]
    result = await db_session.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one()
    customer.is_locked = True
    await db_session.commit()

    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    outcome = await resolve_account_access(ctx, customer_id, confirmed=False, message="I'm locked out")

    assert outcome.pending_confirmation is True
    assert outcome.awaiting_approval is False


async def test_resolve_account_access_locked_confirmed_proposes_unlock_without_applying(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_account_access

    customer_id = seeded_customer["customer_id"]
    result = await db_session.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one()
    customer.is_locked = True
    await db_session.commit()

    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    outcome = await resolve_account_access(ctx, customer_id, confirmed=True, message="I'm locked out")

    assert outcome.awaiting_approval is True
    assert outcome.pending_internal_call == {"tool": "unlock_account", "args": {"customer_id": customer_id}}
    result = await db_session.execute(select(Customer).where(Customer.id == customer_id))
    assert result.scalar_one().is_locked is True  # not applied yet


# --- resolve_billing ---


async def test_resolve_billing_payment_method_redirects_without_accepting_card_details(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_billing

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_billing(
        ctx, customer_id, confirmed=False, message="I want to update my payment method",
        conversation_id="c1", message_id="m1",
    )

    assert any("secure account settings" in fact.lower() for fact in outcome.facts)
    assert outcome.awaiting_approval is False
    assert outcome.tool_calls == []


async def test_resolve_billing_gift_card_escalates(db_session, seeded_customer, seeded_workflow_run):
    from app.agents.resolution import resolve_billing

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_billing(
        ctx, customer_id, confirmed=False, message="My gift card isn't working",
        conversation_id="c1", message_id="m1",
    )

    assert outcome.escalation_reason is not None
    assert "gift card" in outcome.escalation_reason.lower()


async def test_resolve_billing_no_duplicate_found_reports_honestly(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_billing

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_billing(
        ctx, customer_id, confirmed=False, message="I was charged twice for my order!",
        conversation_id="c1", message_id="m1",
    )

    # seeded_customer has exactly one successful payment - no duplicate.
    assert any("no duplicate charge" in fact.lower() for fact in outcome.facts)
    assert outcome.awaiting_approval is False


async def test_resolve_billing_duplicate_charge_proposes_a_refund(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_billing

    customer_id = seeded_customer["customer_id"]
    order_id = await _add_order(db_session, customer_id)
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="succeeded", amount=50.0))
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="succeeded", amount=50.0))
    await db_session.commit()

    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    outcome = await resolve_billing(
        ctx, customer_id, confirmed=False, message="I was charged twice for my order!",
        conversation_id=seeded_workflow_run["conversation_id"], message_id="m1",
    )

    assert outcome.pending_confirmation is True
    assert any("duplicate charge" in fact.lower() for fact in outcome.facts)


async def test_resolve_billing_duplicate_charge_confirmed_creates_refund(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_billing

    customer_id = seeded_customer["customer_id"]
    order_id = await _add_order(db_session, customer_id)
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="succeeded", amount=50.0))
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="succeeded", amount=50.0))
    await db_session.commit()

    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    outcome = await resolve_billing(
        ctx, customer_id, confirmed=True, message="I was charged twice for my order!",
        conversation_id=seeded_workflow_run["conversation_id"], message_id="m2",
    )

    assert outcome.awaiting_approval is True
    assert any(tc["tool"] == "create_refund_request" for tc in outcome.tool_calls)


async def test_duplicate_charge_confirmation_survives_reclassification_to_refund_intent(
    db_session, seeded_customer, seeded_workflow_run
):
    """spec: Phase 13 live-testing bug - the natural confirmation reply
    ("yes, refund the duplicate charge") contains "refund", strong enough
    that a real LLM reclassifies the whole turn as REFUND intent instead
    of BILLING. gather_resolution_facts must route back to
    _resolve_duplicate_charge via the Conversation.metadata_json marker
    regardless of what intent this turn reclassified to - simulated here
    by calling gather_resolution_facts with intent="REFUND" directly,
    exactly what a real misclassification would look like."""
    from app.agents.resolution import gather_resolution_facts

    customer_id = seeded_customer["customer_id"]
    conversation_id = seeded_workflow_run["conversation_id"]
    order_id = await _add_order(db_session, customer_id)
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="succeeded", amount=50.0))
    db_session.add(Payment(order_id=order_id, customer_id=customer_id, status="succeeded", amount=50.0))
    await db_session.commit()
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    first = await gather_resolution_facts(
        ctx, intent="BILLING", customer_id=customer_id, conversation_id=conversation_id,
        message_id="m1", message="I was charged twice for my order!", history=[], retrieved_documents=[],
    )
    assert first.pending_confirmation is True

    # Intent on this turn reclassified to REFUND (a COMMERCE_INTENT with
    # its own storefront routing) - must still land back in the
    # duplicate-charge flow, not resolve_via_storefront/resolve_refund.
    second = await gather_resolution_facts(
        ctx, intent="REFUND", customer_id=customer_id, conversation_id=conversation_id,
        message_id="m2", message="Yes, please refund the duplicate charge.",
        history=[
            {"role": "user", "content": "I was charged twice for my order!"},
            {
                "role": "assistant",
                "content": "Please confirm you would like a refund of the duplicate amount.",
            },
        ],
        retrieved_documents=[],
    )
    assert second.awaiting_approval is True
    assert any(tc["tool"] == "create_refund_request" for tc in second.tool_calls)


async def test_resolve_billing_falls_back_to_knowledge_for_anything_else(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_billing

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_billing(
        ctx, customer_id, confirmed=False, message="Can you send me an invoice for last month?",
        conversation_id="c1", message_id="m1", retrieved_documents=[],
    )

    # No ctx/llm-driven external tool fallback available (llm=None) - the
    # honest "nothing found" escalation, not a crash or silent no-op.
    assert outcome.escalation_reason == "No reliable knowledge found for this question"


# --- resolve_product_information ---


async def test_resolve_product_information_bulk_order_escalates(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_product_information

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_product_information(
        ctx, customer_id, message="I'd like to place a bulk order for resale, 500 units",
    )

    assert outcome.escalation_reason is not None
    assert "sales" in outcome.escalation_reason.lower()


async def test_resolve_product_information_falls_back_to_knowledge(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_product_information

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_product_information(
        ctx, customer_id, message="What material is this made of?", retrieved_documents=[],
    )

    assert outcome.escalation_reason == "No reliable knowledge found for this question"


# --- resolve_order_status: lost-package discrepancy ---


async def test_resolve_order_status_delivered_but_never_arrived_escalates(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_order_status

    customer_id = seeded_customer["customer_id"]
    await _add_order(db_session, customer_id, status="delivered")
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_order_status(
        ctx, customer_id, message="It shows delivered but I never received it!"
    )

    assert outcome.requires_human is True
    reason = (outcome.escalation_reason or "").lower()
    assert "lost package" in reason or "never receiving" in reason


async def test_resolve_order_status_delivered_without_dispute_does_not_escalate(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_order_status

    customer_id = seeded_customer["customer_id"]
    await _add_order(db_session, customer_id, status="delivered")
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_order_status(ctx, customer_id, message="Where is my order?")

    assert outcome.requires_human is False
