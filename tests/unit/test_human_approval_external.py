"""app.workflow.nodes.human_approval._execute_approved_external_call - the
actual MCP/OpenAPI tool execution that happens once (and only once) after
a staff member approves a proposed call. Tested directly (bypassing
human_approval_gate's `interrupt()`, which only works inside a compiled
LangGraph run). MCP cases use a real in-process MCP server (same pattern
as test_mcp_client.py/test_external_tools.py, since there's no
respx-equivalent mock for the MCP session protocol); OpenAPI cases use
respx (already the established pattern for this codebase's REST
integrations - see test_jira_client.py/test_woocommerce_client.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import respx
import uvicorn
from httpx import Response
from mcp.server.mcpserver import MCPServer

from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.repositories.integrations import IntegrationRepository
from app.workflow.deps import WorkflowDeps
from app.workflow.nodes.human_approval import _execute_approved_external_call

_PORT = 8937


def _build_test_server() -> MCPServer:
    server = MCPServer("approval-test-server")

    @server.tool()
    def cancel_subscription(subscription_id: str) -> str:
        """Cancel a subscription by id."""
        return f"Cancelled {subscription_id}"

    @server.tool()
    def boom() -> str:
        """Always raises."""
        raise ValueError("downstream failure")

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


async def _add_mcp_integration(db_session, base_url: str, *, enabled: bool = True) -> Integration:
    integration = Integration(
        id="int_mcp_approval_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Subscriptions MCP",
        type="mcp",
        base_url=base_url,
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "t"}),
        config={},
        enabled=enabled,
        created_by="staff_1",
    )
    return await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)


async def _add_openapi_integration(db_session, *, enabled: bool = True) -> Integration:
    integration = Integration(
        id="int_openapi_approval_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Storefront API",
        type="openapi",
        base_url="https://storefront.example.com",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "t"}),
        config={"spec_url": "https://storefront.example.com/openapi.json"},
        enabled=enabled,
        created_by="staff_1",
    )
    return await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)


def _fake_config(db_session) -> dict:
    deps = WorkflowDeps(session=db_session, llm_router=None, retriever=None)  # type: ignore[arg-type]
    return {"configurable": {"deps": deps}}


@pytest.fixture
async def state(seeded_workflow_run) -> dict:
    return {
        "tenant_id": DEFAULT_TENANT_ID,
        "customer_id": "cust_test",
        "workflow_run_id": seeded_workflow_run["workflow_run_id"],
        "resolution_facts": ["existing fact"],
    }


async def test_executes_the_mcp_tool_and_appends_a_grounded_fact(db_session, mcp_server_url, state):
    integration = await _add_mcp_integration(db_session, mcp_server_url)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "mcp",
        "tool_name": "cancel_subscription",
        "arguments": {"subscription_id": "sub_1"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert "requires_human" not in result
    assert "Cancelled sub_1" in result["resolution_facts"][-1]
    assert "existing fact" in result["resolution_facts"]
    assert "Cancelled sub_1" in result["draft_response"]


async def test_mcp_tool_failure_escalates_instead_of_raising(db_session, mcp_server_url, state):
    integration = await _add_mcp_integration(db_session, mcp_server_url)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "mcp",
        "tool_name": "boom",
        "arguments": {},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "failed" in result["escalation_reason"].lower()


async def test_disabled_integration_escalates(db_session, mcp_server_url, state):
    integration = await _add_mcp_integration(db_session, mcp_server_url, enabled=False)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "mcp",
        "tool_name": "cancel_subscription",
        "arguments": {"subscription_id": "sub_1"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "removed or disabled" in result["escalation_reason"].lower()
    assert "no longer available" in result["draft_response"].lower()


async def test_deleted_integration_escalates(db_session, mcp_server_url, state):
    pending = {
        "integration_id": "does-not-exist",
        "integration_name": "Ghost Integration",
        "source": "mcp",
        "tool_name": "cancel_subscription",
        "arguments": {"subscription_id": "sub_1"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True


@respx.mock
async def test_executes_the_openapi_operation_and_appends_a_grounded_fact(db_session, state):
    integration = await _add_openapi_integration(db_session)
    respx.post("https://storefront.example.com/orders/order_1001/cancel").mock(
        return_value=Response(200, json={"status": "cancelled", "orderId": "order_1001"})
    )
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "openapi",
        "tool_name": "cancelOrder",
        "arguments": {"orderId": "order_1001"},
        "method": "POST",
        "path": "/orders/{orderId}/cancel",
        "param_locations": {"orderId": "path"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert "requires_human" not in result
    assert "cancelled" in result["resolution_facts"][-1]
    assert "cancelled" in result["draft_response"]


@respx.mock
async def test_openapi_failure_reopens_and_escalates_at_source_agnostic_path(db_session, state):
    # Regression test: the exact bug already fixed this session for MCP
    # (a failed approved action silently reading "resolved") must not
    # reappear for the OpenAPI source - app.workflow.runner.resume_workflow
    # reads `requires_human`/`escalation_reason` generically regardless of
    # source, so this only needs to prove the OpenAPI failure path
    # populates them the same way the MCP path already does.
    integration = await _add_openapi_integration(db_session)
    respx.post("https://storefront.example.com/orders/order_1001/cancel").mock(
        return_value=Response(500, text="internal error")
    )
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "openapi",
        "tool_name": "cancelOrder",
        "arguments": {"orderId": "order_1001"},
        "method": "POST",
        "path": "/orders/{orderId}/cancel",
        "param_locations": {"orderId": "path"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "failed" in result["escalation_reason"].lower()


async def test_openapi_disabled_integration_escalates(db_session, state):
    integration = await _add_openapi_integration(db_session, enabled=False)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "openapi",
        "tool_name": "cancelOrder",
        "arguments": {"orderId": "order_1001"},
        "method": "POST",
        "path": "/orders/{orderId}/cancel",
        "param_locations": {"orderId": "path"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "removed or disabled" in result["escalation_reason"].lower()


async def test_missing_source_key_defaults_to_mcp(db_session, mcp_server_url, state):
    # Backward-compatibility: a workflow run interrupted before the
    # `source` key existed (pre-Phase-7) must still resume correctly.
    integration = await _add_mcp_integration(db_session, mcp_server_url)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "tool_name": "cancel_subscription",
        "arguments": {"subscription_id": "sub_1"},
        # no "source" key
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert "requires_human" not in result
    assert "Cancelled sub_1" in result["draft_response"]


# --- Phase 8.2: staff-edited argument overrides ---


@respx.mock
async def test_argument_override_merges_into_proposed_arguments(db_session, state):
    integration = await _add_openapi_integration(db_session)
    route = respx.post("https://storefront.example.com/orders/order_9999/cancel").mock(
        return_value=Response(200, json={"status": "cancelled", "orderId": "order_9999"})
    )
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "openapi",
        "tool_name": "cancelOrder",
        "arguments": {"orderId": "order_1001"},
        "method": "POST",
        "path": "/orders/{orderId}/cancel",
        "param_locations": {"orderId": "path"},
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
    }

    result = await _execute_approved_external_call(
        state, _fake_config(db_session), pending, arguments_override={"orderId": "order_9999"}
    )

    assert "requires_human" not in result
    # The edited order id, not the originally-proposed one, is what
    # actually reached the external call.
    assert route.called
    assert result["execution_result"] == {"result": {"status": "cancelled", "orderId": "order_9999"}}


@respx.mock
async def test_argument_override_failing_schema_validation_escalates_without_calling(db_session, state):
    integration = await _add_openapi_integration(db_session)
    route = respx.post("https://storefront.example.com/orders/order_1001/cancel").mock(
        return_value=Response(200, json={"status": "cancelled"})
    )
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "openapi",
        "tool_name": "cancelOrder",
        "arguments": {"orderId": "order_1001"},
        "method": "POST",
        "path": "/orders/{orderId}/cancel",
        "param_locations": {"orderId": "path"},
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}},
            "required": ["orderId"],
        },
    }

    # Overriding orderId with a non-string fails the tool's real schema -
    # this must be rejected before any HTTP call is attempted, not just
    # at the original LLM-proposal stage.
    result = await _execute_approved_external_call(
        state, _fake_config(db_session), pending, arguments_override={"orderId": 12345}
    )

    assert result["requires_human"] is True
    assert "schema validation" in result["escalation_reason"].lower()
    assert not route.called


async def test_no_override_leaves_proposed_arguments_unchanged(db_session, mcp_server_url, state):
    integration = await _add_mcp_integration(db_session, mcp_server_url)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "mcp",
        "tool_name": "cancel_subscription",
        "arguments": {"subscription_id": "sub_1"},
    }

    result = await _execute_approved_external_call(
        state, _fake_config(db_session), pending, arguments_override=None
    )

    assert "requires_human" not in result
    assert "Cancelled sub_1" in result["draft_response"]


# --- Phase 8.2: execution_result persistence ---


async def test_successful_mcp_call_returns_execution_result(db_session, mcp_server_url, state):
    integration = await _add_mcp_integration(db_session, mcp_server_url)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "mcp",
        "tool_name": "cancel_subscription",
        "arguments": {"subscription_id": "sub_1"},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["execution_result"] == {"text": "Cancelled sub_1"}


async def test_failed_mcp_call_returns_execution_result_with_error(db_session, mcp_server_url, state):
    integration = await _add_mcp_integration(db_session, mcp_server_url)
    pending = {
        "integration_id": integration.id,
        "integration_name": integration.name,
        "source": "mcp",
        "tool_name": "boom",
        "arguments": {},
    }

    result = await _execute_approved_external_call(state, _fake_config(db_session), pending)

    assert result["requires_human"] is True
    assert "error" in result["execution_result"]
