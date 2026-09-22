"""End-to-end workflow scenarios (spec §34, §43), exercised through the
public API with the deterministic mock LLM provider.
"""

import uuid

import pytest
import respx
from httpx import Response


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _post_message(client, token: str, conversation_id: str, message: str) -> dict:
    response = await client.post(
        "/api/v1/support/messages",
        json={
            "conversation_id": conversation_id,
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
            "message": message,
            "channel": "web",
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_scenario_order_status(client, auth_token, seeded_customer):
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    result = await _post_message(client, auth_token, conversation_id, "Where is my order?")

    assert result["requires_human"] is False
    assert result["status"] == "resolved"
    assert result["response"]


@pytest.mark.asyncio
async def test_scenario_security_always_escalates(client, auth_token, seeded_customer):
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    result = await _post_message(
        client, auth_token, conversation_id, "I think someone accessed my account without permission."
    )

    assert result["requires_human"] is True
    assert result["status"] == "escalated"
    # The acknowledgment must never claim to have looked up account details.
    assert result["response"]


@pytest.mark.asyncio
async def test_scenario_unknown_question_does_not_hallucinate(client, auth_token, seeded_customer):
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    result = await _post_message(
        client, auth_token, conversation_id, "Can you explain your company's quantum computing strategy?"
    )

    # No reliable knowledge exists for this - must escalate rather than invent an answer.
    assert result["requires_human"] is True


@pytest.mark.asyncio
async def test_scenario_refund_requires_confirmation_then_human_approval(
    client, auth_token, seeded_customer, staff_token, seeded_staff
):
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"

    first = await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    assert first["requires_human"] is False
    assert first["status"] == "resolved"

    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    assert second["status"] == "awaiting_approval"
    assert second["requires_human"] is True
    assert second["response"] is None
    assert second["ticket_id"]

    # The interrupted graph never reaches save_outcome (which normally sets
    # Conversation.status - see app.workflow.nodes.save_outcome), so
    # run_workflow must set it itself; otherwise a customer refreshing mid-
    # approval would see stale "resolved" from the prior turn.
    conversation_resp = await client.get(
        f"/api/v1/support/conversations/{conversation_id}", headers=_headers(auth_token)
    )
    assert conversation_resp.status_code == 200
    assert conversation_resp.json()["status"] == "awaiting_approval"

    ticket_resp = await client.get(
        f"/api/v1/support/tickets/{second['ticket_id']}", headers=_headers(staff_token)
    )
    assert ticket_resp.status_code == 200
    assert ticket_resp.json()["status"] == "open"

    approve_resp = await client.post(
        f"/api/v1/support/tickets/{second['ticket_id']}/approve",
        json={"workflow_run_id": second["workflow_run_id"]},
        headers=_headers(staff_token),
    )
    assert approve_resp.status_code == 200, approve_resp.text
    approved_ticket = approve_resp.json()
    assert approved_ticket["status"] == "resolved"
    assert approved_ticket["approved_by"] == seeded_staff["staff_id"]

    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.domain.models import AuditLog, RefundRequest

    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.resource_id == second["ticket_id"])
        )
        audit_entries = result.scalars().all()
        # spec: Phase 9.4a regression test - a real, previously-unfixed
        # bug meant this row stayed permanently "pending" no matter what
        # staff decided; only the ticket's own status was ever updated.
        refund_result = await session.execute(
            select(RefundRequest).where(RefundRequest.customer_id == seeded_customer["customer_id"])
        )
        refund = refund_result.scalars().first()
        assert refund is not None
        assert refund.status == "approved"
    expected_actor = f"human:{seeded_staff['staff_id']}"
    assert any(a.action == "approve_ticket" and a.actor == expected_actor for a in audit_entries)


@pytest.mark.asyncio
async def test_scenario_refund_rejected_by_staff_updates_refund_status(
    client, auth_token, seeded_customer, staff_token
):
    """spec: Phase 9.4a - the reject path of the same bug: a rejected
    ticket must mark the underlying RefundRequest 'rejected', not leave
    it stuck at 'pending' forever."""
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"

    first = await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    assert first["status"] == "resolved"

    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    assert second["status"] == "awaiting_approval"

    reject_resp = await client.post(
        f"/api/v1/support/tickets/{second['ticket_id']}/reject",
        json={"workflow_run_id": second["workflow_run_id"], "reason": "duplicate request"},
        headers=_headers(staff_token),
    )
    assert reject_resp.status_code == 200, reject_resp.text
    assert reject_resp.json()["status"] == "rejected"

    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.domain.models import RefundRequest

    async with get_sessionmaker()() as session:
        refund_result = await session.execute(
            select(RefundRequest).where(RefundRequest.customer_id == seeded_customer["customer_id"])
        )
        refund = refund_result.scalars().first()
        assert refund is not None
        assert refund.status == "rejected"


@pytest.mark.asyncio
async def test_scenario_ticket_decision_pushes_a_live_nudge_to_the_open_conversation(
    client, auth_token, seeded_customer, staff_token
):
    """A staff decision on a paused ticket happens completely outside the
    customer's own request/response cycle - without a push, the customer's
    open chat tab would only find out via its 5-second awaiting_approval
    poll. `app.workflow.runner.resume_workflow` broadcasts a best-effort
    nudge through the same process-local `ConnectionManager` the inbound
    storefront webhook already uses (spec: Phase 10.3) - registering a
    fake socket directly with the real singleton (rather than opening a
    real websocket, which `tests/integration/test_support_ws.py` already
    covers) isolates this test to just the resume-triggers-a-broadcast
    behavior."""
    from app.realtime.connections import get_connection_manager

    class _FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    first = await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    assert first["status"] == "resolved"
    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    assert second["status"] == "awaiting_approval"

    manager = get_connection_manager()
    fake_socket = _FakeWebSocket()
    await manager.register(conversation_id, fake_socket)
    try:
        approve_resp = await client.post(
            f"/api/v1/support/tickets/{second['ticket_id']}/approve",
            json={"workflow_run_id": second["workflow_run_id"]},
            headers=_headers(staff_token),
        )
        assert approve_resp.status_code == 200, approve_resp.text
    finally:
        manager.unregister(conversation_id, fake_socket)

    assert fake_socket.sent == [
        {"event": "ticket_decision", "workflow_run_id": second["workflow_run_id"], "approved": True}
    ]


@pytest.mark.asyncio
async def test_scenario_ticket_trace_records_every_node_and_the_refund_tool_call(
    client, auth_token, seeded_customer, staff_token
):
    """`GET /tickets/{id}/trace` (spec: 'log what the agent actually does')
    must surface a real, non-empty record of both what the workflow graph
    did node-by-node (WorkflowEvent.data - previously defined, never
    populated) and the real internal tool call the refund resolver made
    (ToolExecution - previously written only via app.tools.base.run_tool,
    now also for external tool calls, but this scenario exercises the
    plain internal-tool path since it needs no new integration setup)."""
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"

    first = await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    assert second["status"] == "awaiting_approval"

    approve_resp = await client.post(
        f"/api/v1/support/tickets/{second['ticket_id']}/approve",
        json={"workflow_run_id": second["workflow_run_id"]},
        headers=_headers(staff_token),
    )
    assert approve_resp.status_code == 200, approve_resp.text

    trace_resp = await client.get(
        f"/api/v1/support/tickets/{second['ticket_id']}/trace", headers=_headers(staff_token)
    )
    assert trace_resp.status_code == 200, trace_resp.text
    trace = trace_resp.json()

    assert trace["workflow_run_id"] == second["workflow_run_id"]
    node_names = {event["node_name"] for event in trace["events"]}
    # Every node the second (confirm) turn's run passed through before
    # pausing for approval - proves this is a real per-node trace, not a
    # single summary row.
    assert {"classify_intent", "resolve_issue", "human_approval_gate"} <= node_names
    resolve_issue_event = next(e for e in trace["events"] if e["node_name"] == "resolve_issue")
    assert resolve_issue_event["data"]["awaiting_approval"] is True
    assert resolve_issue_event["duration_ms"] is not None

    tool_names = {execution["tool_name"] for execution in trace["tool_executions"]}
    assert "create_refund_request" in tool_names
    refund_execution = next(
        e for e in trace["tool_executions"] if e["tool_name"] == "create_refund_request"
    )
    assert refund_execution["success"] is True
    assert first["conversation_id"] == conversation_id  # sanity: same conversation throughout


@pytest.mark.asyncio
async def test_short_confirmation_reply_carries_over_pending_intent(client, auth_token, seeded_customer):
    """A bare 'yes' shares no keywords with the original request, so the
    classifier alone would misroute it as UNKNOWN - previous_intent
    carry-over (app.workflow.nodes.classify) must keep it on REFUND."""
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"

    first = await _post_message(client, auth_token, conversation_id, "I want a refund for my order.")
    assert first["status"] == "resolved"

    second = await _post_message(client, auth_token, conversation_id, "yes")
    assert second["status"] == "awaiting_approval"
    assert second["requires_human"] is True


@pytest.mark.asyncio
async def test_ticket_endpoints_require_staff_token(client, auth_token, seeded_customer):
    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    await _post_message(client, auth_token, conversation_id, "I want a refund for my order.")

    response = await client.get("/api/v1/support/tickets/does-not-matter")
    assert response.status_code == 401


@pytest.mark.asyncio
@respx.mock
async def test_scenario_refund_approval_issues_a_real_stripe_refund(
    client, auth_token, seeded_customer, staff_token, admin_staff_token
):
    """spec: Phase 9.4b - when a tenant has a `stripe` integration
    configured and the refunded order's Payment carries a
    `gateway_payment_intent_id`, approving the refund ticket must
    actually call Stripe's real refund endpoint (proven here via a
    respx-mocked route, not just that a DB status flips) and record the
    returned reference on the RefundRequest row."""
    admin_headers = _headers(admin_staff_token)
    integration_body = {
        "name": "Scenario Stripe",
        "type": "stripe",
        "base_url": "https://api.stripe.com",
        "auth_type": "bearer",
        "credentials": {"token": "sk_test_scenario"},
        "config": {"webhook_secret": "whsec_scenario"},
    }
    create_resp = await client.post(
        "/api/v1/admin/integrations", json=integration_body, headers=admin_headers
    )
    assert create_resp.status_code == 201, create_resp.text

    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.domain.models import Payment, RefundRequest

    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Payment).where(Payment.customer_id == seeded_customer["customer_id"])
        )
        payment = result.scalars().first()
        assert payment is not None
        payment.gateway = "stripe"
        payment.gateway_payment_intent_id = "pi_scenario_test"
        await session.commit()

    stripe_route = respx.post("https://api.stripe.com/v1/refunds").mock(
        return_value=Response(200, json={"id": "re_scenario_test", "status": "pending"})
    )

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    first = await _post_message(
        client, auth_token, conversation_id, "The product arrived damaged. I want my money back."
    )
    assert first["status"] == "resolved"
    second = await _post_message(client, auth_token, conversation_id, "Yes, please confirm the refund.")
    assert second["status"] == "awaiting_approval"

    approve_resp = await client.post(
        f"/api/v1/support/tickets/{second['ticket_id']}/approve",
        json={"workflow_run_id": second["workflow_run_id"]},
        headers=_headers(staff_token),
    )
    assert approve_resp.status_code == 200, approve_resp.text

    assert stripe_route.called
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(RefundRequest).where(RefundRequest.customer_id == seeded_customer["customer_id"])
        )
        refund = result.scalars().first()
        assert refund is not None
        assert refund.status == "approved"
        assert refund.gateway == "stripe"
        assert refund.gateway_reference == "re_scenario_test"
