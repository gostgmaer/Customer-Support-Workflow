"""app.workflow.runner.resume_workflow: an approved MCP tool call that
fails during execution must reopen its ticket, not silently mark it
resolved - a failed action is exactly the anomaly a human needs to see in
their queue. Regression test for a live-testing finding: before this fix,
`resume_workflow` set `ticket.status = "resolved" if approved else "rejected"`
unconditionally, ignoring whether the approved action actually succeeded.

MOCK_LLM's ExternalToolSelection builder always declines (see
app.llm.providers.mock's docstring - real tool selection needs a real
LLM), so `app.agents.resolution.propose_external_tool_call` is
monkeypatched directly here to force a proposal without depending on real
LLM reasoning - this test is about the ticket-reopening behavior, not
selection quality (already covered by tests/unit/test_external_tools.py).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

from app.agents.external_tools import ExternalToolProposal
from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.repositories.integrations import IntegrationRepository

_PORT = 8938


def _build_test_server() -> MCPServer:
    server = MCPServer("anomaly-test-server")

    @server.tool()
    def boom() -> str:
        """Always raises."""
        raise ValueError("downstream failure")

    @server.tool()
    def echo(value: str) -> str:
        """Echoes back whatever value it was called with."""
        return f"echo:{value}"

    return server


@pytest.fixture
async def mcp_server_url() -> AsyncIterator[str]:
    app = _build_test_server().streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        raise RuntimeError("test MCP server did not start in time")

    yield f"http://127.0.0.1:{_PORT}/mcp"

    server.should_exit = True
    await task


@pytest.mark.asyncio
async def test_failed_mcp_execution_reopens_the_ticket_instead_of_resolving(
    client, monkeypatch, db_session, seeded_customer, auth_token, staff_token, mcp_server_url
):
    integration = Integration(
        id="int_anomaly_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Anomaly Test MCP",
        type="mcp",
        base_url=mcp_server_url,
        auth_type="none",
        encrypted_credentials=encode_credentials({}),
        config={},
        enabled=True,
        created_by="staff_1",
    )
    await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)
    await db_session.commit()

    async def _fake_propose(ctx, llm, message):  # noqa: ANN001, ARG001
        return ExternalToolProposal(
            integration_id=integration.id,
            integration_name=integration.name,
            source="mcp",
            tool_name="boom",
            arguments={},
        )

    monkeypatch.setattr("app.agents.resolution.propose_external_tool_call", _fake_propose)

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    propose_response = await client.post(
        "/api/v1/support/messages",
        json={
            "conversation_id": conversation_id,
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
            "message": "asdkj qwoeiruqwoe random nonsense not in the knowledge base",
            "channel": "web",
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert propose_response.status_code == 200, propose_response.text
    proposed = propose_response.json()
    assert proposed["status"] == "awaiting_approval"
    ticket_id = proposed["ticket_id"]
    workflow_run_id = proposed["workflow_run_id"]

    approve_response = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/approve",
        json={"workflow_run_id": workflow_run_id},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text
    approved_ticket = approve_response.json()

    # The core assertion: a failed *approved* action must NOT read
    # "resolved" - that would hide a real anomaly from the staff queue.
    assert approved_ticket["status"] == "open"
    assert "failed" in approved_ticket["reason_for_escalation"].lower()
    assert approved_ticket["approved_by"] is not None
    # A failed approved action is more urgent than a plain "I don't know"
    # escalation - priority should be bumped up, never left at whatever
    # low/medium priority the original (non-failure) proposal had.
    assert approved_ticket["priority"] in ("HIGH", "CRITICAL")


@pytest.mark.asyncio
async def test_ticket_carries_pending_call_and_approve_can_override_arguments(
    client, monkeypatch, db_session, seeded_customer, auth_token, staff_token, mcp_server_url
):
    """spec: Phase 8.2 - the ticket the queue shows must carry the
    structured proposed call (not just flattened summary text), and
    staff approving with an `arguments` override must have the OVERRIDE,
    not the original AI-proposed value, actually reach the external call
    - proven end-to-end through the real HTTP approve route, not just the
    lower-level _execute_approved_external_call unit tests."""
    integration = Integration(
        id="int_anomaly_2",
        tenant_id=DEFAULT_TENANT_ID,
        name="Echo Test MCP",
        type="mcp",
        base_url=mcp_server_url,
        auth_type="none",
        encrypted_credentials=encode_credentials({}),
        config={},
        enabled=True,
        created_by="staff_1",
    )
    await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)
    await db_session.commit()

    async def _fake_propose(ctx, llm, message):  # noqa: ANN001, ARG001
        return ExternalToolProposal(
            integration_id=integration.id,
            integration_name=integration.name,
            source="mcp",
            tool_name="echo",
            arguments={"value": "original"},
        )

    monkeypatch.setattr("app.agents.resolution.propose_external_tool_call", _fake_propose)

    conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    propose_response = await client.post(
        "/api/v1/support/messages",
        json={
            "conversation_id": conversation_id,
            "message_id": f"msg_{uuid.uuid4().hex[:8]}",
            "message": "asdkj qwoeiruqwoe random nonsense not in the knowledge base",
            "channel": "web",
        },
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert propose_response.status_code == 200, propose_response.text
    proposed = propose_response.json()
    ticket_id = proposed["ticket_id"]
    workflow_run_id = proposed["workflow_run_id"]

    ticket_response = await client.get(
        f"/api/v1/support/tickets/{ticket_id}", headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert ticket_response.status_code == 200, ticket_response.text
    ticket_before_approval = ticket_response.json()
    assert ticket_before_approval["pending_call"] == {
        "integration_name": "Echo Test MCP",
        "tool_name": "echo",
        "arguments": {"value": "original"},
    }
    assert ticket_before_approval["execution_result"] is None

    approve_response = await client.post(
        f"/api/v1/support/tickets/{ticket_id}/approve",
        json={"workflow_run_id": workflow_run_id, "arguments": {"value": "edited-by-staff"}},
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert approve_response.status_code == 200, approve_response.text
    approved_ticket = approve_response.json()

    assert approved_ticket["status"] == "resolved"
    # The edited value, not the AI-proposed "original", is what actually
    # reached the MCP tool.
    assert approved_ticket["execution_result"] == {"text": "echo:edited-by-staff"}
