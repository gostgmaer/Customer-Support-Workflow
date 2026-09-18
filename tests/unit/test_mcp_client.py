"""app.integrations.mcp_client - exercised against a real in-process MCP
server (mcp.server.mcpserver.MCPServer over Streamable HTTP via uvicorn),
not a mock - there's no respx-equivalent for the MCP session protocol, and
a real round trip is what actually proves the transport/auth wiring works,
matching how this feature was hand-verified during development."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import uvicorn
from mcp.server.mcpserver import Context, MCPServer

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.mcp_client import call_tool, list_tools

_PORT = 8935


def _build_test_server() -> MCPServer:
    server = MCPServer("test-server")

    @server.tool()
    def echo(text: str) -> str:
        """Echo the given text back."""
        return f"echo: {text}"

    @server.tool()
    def boom(text: str) -> str:
        """Always raises."""
        raise ValueError("boom failure")

    @server.tool()
    def whoami(ctx: Context) -> str:
        """Returns the Authorization header the request arrived with."""
        return ctx.headers.get("authorization", "none")

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


def _mcp_integration(base_url: str, *, auth_type: str = "bearer", token: str = "test-token") -> Integration:
    creds = {"token": token} if auth_type == "bearer" else {"api_key": token}
    return Integration(
        id="int_mcp_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test MCP Server",
        type="mcp",
        base_url=base_url,
        auth_type=auth_type,
        encrypted_credentials=encode_credentials(creds),
        config={},
        enabled=True,
        created_by="staff_1",
    )


async def test_list_tools_returns_discovered_tools(mcp_server_url: str):
    tools = await list_tools(_mcp_integration(mcp_server_url))

    names = {t.name for t in tools}
    assert names == {"echo", "boom", "whoami"}
    echo_tool = next(t for t in tools if t.name == "echo")
    assert echo_tool.input_schema["properties"]["text"]["type"] == "string"


async def test_call_tool_returns_text_result(mcp_server_url: str):
    result = await call_tool(_mcp_integration(mcp_server_url), "echo", {"text": "hello"})

    assert result["text"] == "echo: hello"


async def test_call_tool_raises_integration_error_on_tool_failure(mcp_server_url: str):
    with pytest.raises(IntegrationError):
        await call_tool(_mcp_integration(mcp_server_url), "boom", {"text": "x"})


async def test_call_tool_raises_integration_error_on_unknown_tool(mcp_server_url: str):
    with pytest.raises(IntegrationError):
        await call_tool(_mcp_integration(mcp_server_url), "does_not_exist", {})


async def test_bearer_token_reaches_the_server(mcp_server_url: str):
    integration = _mcp_integration(mcp_server_url, auth_type="bearer", token="secret-token-123")

    result = await call_tool(integration, "whoami", {})

    assert result["text"] == "Bearer secret-token-123"


async def test_api_key_uses_configurable_header(mcp_server_url: str):
    integration = _mcp_integration(mcp_server_url, auth_type="api_key", token="key-abc")
    integration.config = {"api_key_header": "X-Api-Key"}

    result = await call_tool(integration, "whoami", {})

    # whoami only reads Authorization - a custom header name means the
    # server sees no Authorization header at all, proving the client sent
    # the credential under the configured header name, not the default.
    assert result["text"] == "none"


async def test_none_auth_sends_no_authorization_header(mcp_server_url: str):
    # Regression test: live-verified against mcp.deepwiki.com, which
    # *rejects* a call carrying any Authorization header at all (even an
    # unused placeholder one) with "Authentication is not allowed on the
    # public [...] endpoint". auth_type="none" must omit the header
    # entirely, not just send an empty value.
    integration = _mcp_integration(mcp_server_url, auth_type="none")

    result = await call_tool(integration, "whoami", {})

    assert result["text"] == "none"


async def test_basic_auth_rejected():
    # CreateIntegrationRequest already rejects auth_type="basic" for
    # type="mcp" at the API layer (see
    # tests/integration/test_integrations_api.py::test_mcp_integration_rejects_basic_auth)
    # - this covers a row that predates that validation, or was corrupted.
    integration = _mcp_integration("http://127.0.0.1:1/mcp", auth_type="bearer", token="unused")
    integration.auth_type = "basic"

    with pytest.raises(IntegrationError):
        await list_tools(integration)
