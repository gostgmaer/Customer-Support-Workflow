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


async def _add_order(
    db_session,
    customer_id: str,
    *,
    status: str,
    total_amount: float = 100.0,
    estimated_delivery: datetime | None = None,
) -> str:
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
            estimated_delivery=estimated_delivery,
        )
    )
    await db_session.flush()
    await db_session.commit()
    return order_id


# --- 8.3a: partial refunds ---


async def test_extract_requested_amount_treats_zero_as_no_amount_stated():
    """spec: Phase 12 audit - a $0 (or mis-extracted trivial) amount must
    fall back to "no amount stated" (a full refund), not create a real,
    pointless $0 refund request."""
    from app.agents.resolution import _extract_requested_amount

    assert _extract_requested_amount("I'd like a $0 refund", 100.0) is None


async def test_extract_requested_amount_never_captures_a_negative_sign():
    """The regex has no '-' in its character class, so "-$50" matches only
    the digits after the '$' - documenting/locking in that this can never
    produce a negative amount, rather than assuming it from reading the
    regex alone."""
    from app.agents.resolution import _extract_requested_amount

    assert _extract_requested_amount("-$50 refund please", 100.0) == 50.0


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


# --- Phase 13: subscription-cancellation policy check (Subscription Policy's
# real "annual plan, cancel within 14 days -> prorated refund, not a plain
# cancellation" rule) ---


class _StubEligibilityLLM:
    def __init__(self, qualifies: str) -> None:
        self._qualifies = qualifies

    async def generate(self, *a, **k):
        raise NotImplementedError

    async def generate_structured(self, messages, *, schema, max_tokens=1024, usage_callback=None):
        from app.agents.policy_check import CommerceEligibilityCheck

        return CommerceEligibilityCheck(qualifies=self._qualifies, reason="stub")


class _StubSubscriptionPolicyRetriever:
    async def retrieve(self, query: str, *, tenant_id: str, top_k: int = 4, **_):
        from app.rag.retriever import RetrievedDocument

        return [
            RetrievedDocument(
                document_id="doc_sub", chunk_id="c1", title="Subscription Policy",
                source="subscription_policy.md", category="subscription",
                text="Annual-plan customers cancelling within 14 days qualify for a prorated refund.",
                score=0.9,
            )
        ]


async def test_resolve_subscription_cancel_qualifying_for_refund_escalates_instead_of_cancelling(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_subscription

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_subscription(
        ctx, customer_id, message="please cancel my subscription", confirmed=True, history=[],
        llm=_StubEligibilityLLM("yes"), retriever=_StubSubscriptionPolicyRetriever(),
    )

    assert outcome.escalation_reason is not None
    assert "prorated refund" in outcome.escalation_reason.lower()
    # Must NOT have actually cancelled it.
    assert not any(tc["tool"] == "update_subscription" for tc in outcome.tool_calls)


async def test_resolve_subscription_cancel_not_qualifying_proceeds_normally(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_subscription

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_subscription(
        ctx, customer_id, message="please cancel my subscription", confirmed=True, history=[],
        llm=_StubEligibilityLLM("no"), retriever=_StubSubscriptionPolicyRetriever(),
    )

    assert any(tc["tool"] == "update_subscription" for tc in outcome.tool_calls)


async def test_resolve_subscription_cancel_without_llm_or_retriever_skips_the_gate(
    db_session, seeded_customer, seeded_workflow_run
):
    """No llm/retriever passed (the common case in most of this file's
    other tests, and MOCK_LLM-driven test runs) - degrades to the
    pre-Phase-13 unconditional-cancel behavior, exactly like resolve_refund's
    equivalent gate already does."""
    from app.agents.resolution import resolve_subscription

    customer_id = seeded_customer["customer_id"]
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_subscription(
        ctx, customer_id, message="please cancel my subscription", confirmed=True, history=[],
    )

    assert any(tc["tool"] == "update_subscription" for tc in outcome.tool_calls)


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


# --- Phase 12: RAG policy-check gate on resolve_refund ---


class _StubEligibilityLLM:
    def __init__(self, qualifies: str, reason: str = "stub") -> None:
        self._qualifies = qualifies
        self._reason = reason
        self.calls = 0

    async def generate(self, *a, **k):
        raise NotImplementedError

    async def generate_structured(self, messages, *, schema, max_tokens=1024, usage_callback=None):
        from app.agents.policy_check import CommerceEligibilityCheck

        assert schema is CommerceEligibilityCheck
        self.calls += 1
        return CommerceEligibilityCheck(qualifies=self._qualifies, reason=self._reason)


class _StubPolicyRetriever:
    def __init__(self, doc) -> None:
        self._doc = doc
        self.calls = 0

    async def retrieve(self, query, *, tenant_id, top_k=4, **_):
        self.calls += 1
        return [self._doc] if self._doc else []


def _refund_policy_doc():
    from app.rag.retriever import RetrievedDocument

    return RetrievedDocument(
        document_id="doc_1", chunk_id="c1", title="Refund Policy", source="refund_policy.md",
        category="refunds", text="Full refund within 30 days of delivery.", score=0.9,
    )


async def test_resolve_refund_policy_gate_denies_and_never_creates_a_refund_request(
    db_session, seeded_customer, seeded_workflow_run
):
    """A clear policy denial must stop before create_refund_request is ever
    called - asserted the same way this project's other approval-gate
    tests assert "never called before approval" (no RefundRequest row
    exists afterward), not just by reading the returned facts."""
    from sqlalchemy import select

    from app.agents.resolution import resolve_refund
    from app.domain.models import RefundRequest

    customer_id = seeded_customer["customer_id"]
    order_id = await _add_order(
        db_session, customer_id, status="delivered",
        estimated_delivery=datetime.now(UTC) - timedelta(days=90),
    )
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    llm = _StubEligibilityLLM("no", reason="Delivered 90 days ago, past the 30-day refund window")
    retriever = _StubPolicyRetriever(_refund_policy_doc())

    outcome = await resolve_refund(
        ctx, customer_id, confirmed=True, conversation_id="conv_1", message_id="m1",
        message="I'd like a refund please.", history=[], llm=llm, retriever=retriever,
    )

    assert all(call["tool"] != "create_refund_request" for call in outcome.tool_calls)
    assert any("30-day" in fact for fact in outcome.facts)
    assert llm.calls == 1
    stmt = select(RefundRequest).where(RefundRequest.order_id == order_id)
    existing = (await db_session.execute(stmt)).all()
    assert existing == []


async def test_resolve_refund_policy_gate_allows_and_proceeds_normally(
    db_session, seeded_customer, seeded_workflow_run
):
    from app.agents.resolution import resolve_refund

    customer_id = seeded_customer["customer_id"]
    await _add_order(
        db_session, customer_id, status="delivered",
        estimated_delivery=datetime.now(UTC) - timedelta(days=3),
    )
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])
    llm = _StubEligibilityLLM("yes", reason="Within the 30-day window")
    retriever = _StubPolicyRetriever(_refund_policy_doc())

    outcome = await resolve_refund(
        ctx, customer_id, confirmed=True, conversation_id="conv_1", message_id="m1",
        message="I'd like a refund please.", history=[], llm=llm, retriever=retriever,
    )

    assert any("refund request" in fact.lower() for fact in outcome.facts)
    assert outcome.awaiting_approval is True


async def test_resolve_refund_without_llm_or_retriever_skips_the_gate_entirely(
    db_session, seeded_customer, seeded_workflow_run
):
    """Every pre-existing test in this file calls resolve_refund with no
    llm/retriever at all - confirms that stays true (today's unconditional
    behavior, unchanged) rather than silently regressing to always-deny."""
    from app.agents.resolution import resolve_refund

    customer_id = seeded_customer["customer_id"]
    await _add_order(
        db_session, customer_id, status="delivered",
        estimated_delivery=datetime.now(UTC) - timedelta(days=90),
    )
    ctx = await _ctx(db_session, customer_id, seeded_workflow_run["workflow_run_id"])

    outcome = await resolve_refund(
        ctx, customer_id, confirmed=True, conversation_id="conv_1", message_id="m1",
        message="I'd like a refund please.", history=[],
    )

    assert any("refund request" in fact.lower() for fact in outcome.facts)
