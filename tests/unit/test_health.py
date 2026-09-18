"""app.integrations.health.test_connection's mcp branch (spec: Phase
10.2) - persists discovered tools into config.discovered_tools, mirroring
the openapi branch's existing config.spec_cache pattern. Monkeypatches
mcp_list_tools directly rather than standing up a real in-process MCP
server (tests/unit/test_mcp_client.py already proves the real transport
works) - this test is only about health.py's own persistence logic.
"""

from __future__ import annotations

import app.integrations.health as health_module
from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.mcp_client import McpToolSpec


def _mcp_integration() -> Integration:
    return Integration(
        id="int_mcp_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test MCP Server",
        type="mcp",
        base_url="https://mcp.example.com/mcp",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "test-token"}),
        config={},
        enabled=True,
        created_by="staff_1",
    )


async def test_mcp_branch_persists_discovered_tools_into_config(monkeypatch):
    tools = [
        McpToolSpec(name="echo", description="Echo the given text back.", input_schema={}),
        McpToolSpec(name="whoami", description="Returns the caller's identity.", input_schema={}),
    ]

    async def _fake_list_tools(integration: Integration) -> list[McpToolSpec]:
        return tools

    monkeypatch.setattr(health_module, "mcp_list_tools", _fake_list_tools)
    integration = _mcp_integration()

    ok, message = await health_module.test_connection(integration)

    assert ok is True
    assert "echo" in message
    assert integration.config["discovered_tools"] == [
        {"name": "echo", "description": "Echo the given text back."},
        {"name": "whoami", "description": "Returns the caller's identity."},
    ]
    assert "discovered_tools_cached_at" in integration.config


async def test_mcp_branch_with_no_tools_persists_an_empty_list(monkeypatch):
    async def _fake_list_tools(integration: Integration) -> list[McpToolSpec]:
        return []

    monkeypatch.setattr(health_module, "mcp_list_tools", _fake_list_tools)
    integration = _mcp_integration()

    ok, message = await health_module.test_connection(integration)

    assert ok is True
    assert "no tools" in message
    assert integration.config["discovered_tools"] == []
