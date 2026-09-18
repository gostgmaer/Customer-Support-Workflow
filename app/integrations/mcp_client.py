"""Client for remote MCP (Model Context Protocol) servers (spec: Phase 6
MCP integration).

Only Streamable HTTP is supported - not stdio. Stdio would mean the API
container spawning and trusting an arbitrary local subprocess per tenant
config, which is a materially worse security posture than an outbound
HTTPS call to a configured endpoint, and doesn't fit a multi-tenant
hosted backend the way it fits a local desktop MCP client.

Every call opens and tears down its own session (list_tools/call_tool are
infrequent - once per admin "Test" click, once per agent tool proposal,
once per staff approval) rather than pooling a long-lived connection per
integration, keeping this consistent with app.integrations.base's
one-client-per-call pattern for the REST integrations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import get_credentials

# list_tools is a fast metadata call - short timeout keeps a bad/unreachable
# server from hanging the admin "Test" button or a tool-selection catalog
# lookup. call_tool is different: live-verified against DeepWiki's
# `ask_question`, which runs its own AI generation server-side and can
# legitimately take 40-70+ seconds - a short timeout here doesn't protect
# anything, it just turns real, in-progress work into a false "anomaly"
# ticket (see app.workflow.nodes.human_approval).
_LIST_TOOLS_TIMEOUT_SECONDS = 15.0
_CALL_TOOL_TIMEOUT_SECONDS = 90.0


def _auth_headers(integration: Integration) -> dict[str, str]:
    if integration.auth_type == "none":
        # Live-verified against mcp.deepwiki.com: some genuinely public MCP
        # servers *reject* a request carrying any Authorization header at
        # all (their tool returns "Authentication is not allowed on the
        # public [...] endpoint"), rather than just ignoring an unused one
        # - so "none" must mean literally no header, not an empty-valued one.
        return {}
    creds = get_credentials(integration)
    if integration.auth_type == "api_key":
        header_name = integration.config.get("api_key_header", "Authorization")
        return {header_name: creds.get("api_key", "")}
    if integration.auth_type == "bearer":
        return {"Authorization": f"Bearer {creds.get('token', '')}"}
    # CreateIntegrationRequest already rejects "basic" for type="mcp" - an
    # unknown auth_type reaching here means a row was created before that
    # validation existed, or corrupted; fail loudly rather than connect
    # unauthenticated.
    raise IntegrationError(
        f"MCP integrations support api_key, bearer, or none auth only (got '{integration.auth_type}')"
    )


@dataclass
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@asynccontextmanager
async def _session(integration: Integration, *, timeout: float) -> AsyncIterator[ClientSession]:
    headers = _auth_headers(integration)
    async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client:
        async with streamable_http_client(integration.base_url, http_client=http_client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
                await session.initialize()
                yield session


async def list_tools(integration: Integration) -> list[McpToolSpec]:
    """Used by the admin "Test" flow (app.integrations.health) and by
    app.agents.external_tools's tool-selection fallback - both need the
    live catalog, not a cached one, since a server's tools can change
    without this integration row changing."""
    try:
        async with _session(integration, timeout=_LIST_TOOLS_TIMEOUT_SECONDS) as session:
            result = await session.list_tools()
    except IntegrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(f"Could not list tools from MCP server '{integration.name}': {exc}") from exc
    return [
        McpToolSpec(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.input_schema or {"type": "object", "properties": {}},
        )
        for tool in result.tools
    ]


def _result_text(result: Any) -> str:
    parts = [block.text for block in (result.content or []) if getattr(block, "text", None)]
    return "\n".join(parts)


async def call_tool(integration: Integration, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Only ever called from app.workflow.nodes.human_approval, after a
    staff member has approved the proposed call - never speculatively, and
    never before approval (see app.agents.external_tools's docstring for
    why: an MCP tool's real-world side effects are unknown at connect
    time, unlike this codebase's other tools which are reviewed code)."""
    try:
        async with _session(integration, timeout=_CALL_TOOL_TIMEOUT_SECONDS) as session:
            result = await session.call_tool(
                tool_name, arguments, read_timeout_seconds=_CALL_TOOL_TIMEOUT_SECONDS
            )
    except IntegrationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IntegrationError(f"MCP tool call '{tool_name}' failed: {exc}") from exc
    text = _result_text(result)
    if result.is_error:
        raise IntegrationError(f"MCP tool '{tool_name}' returned an error: {text or 'unknown error'}")
    return {"text": text, "structured": result.structured_content}
