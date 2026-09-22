"""app.agents.external_tools.propose_external_tool_call - the bounded
tool-selection fallback (spec: Phase 6 MCP integration, Phase 7
generalized to also cover OpenAPI-described REST APIs). Uses a stub LLM
(not MockLLMProvider, which always declines for this schema - see
app.llm.providers.mock's docstring) so these tests can exercise real
selection/validation logic, and a real in-process MCP server (same
fixture pattern as test_mcp_client.py) so the discovered tool catalog is
genuine, not hand-constructed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

from app.agents.external_tools import _describe_arguments, _discover_catalog, propose_external_tool_call
from app.agents.schemas import ExternalToolSelection
from app.db.base import DEFAULT_TENANT_ID
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.llm.base import LLMMessage, UsageCallback
from app.repositories.integrations import IntegrationRepository
from app.tools.base import ToolContext

_PORT = 8936


def _build_test_server() -> MCPServer:
    server = MCPServer("resolution-test-server")

    @server.tool()
    def get_shipping_carrier(order_id: str) -> str:
        """Look up which shipping carrier is handling an order."""
        return f"Carrier for {order_id}: FastShip"

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


@pytest.fixture
async def mcp_ctx(db_session) -> ToolContext:
    return ToolContext(
        session=db_session,
        requesting_customer_id="cust_1",
        workflow_run_id="wf_1",
        tenant_id=DEFAULT_TENANT_ID,
    )


async def _add_enabled_mcp_integration(db_session, base_url: str) -> None:
    integration = Integration(
        id="int_mcp_resolution_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Shipping MCP",
        type="mcp",
        base_url=base_url,
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "t"}),
        config={},
        enabled=True,
        created_by="staff_1",
    )
    await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)


async def _add_enabled_openapi_integration(
    db_session, *, spec_cache: list[dict] | None = None, config_extra: dict | None = None
) -> None:
    if spec_cache is None:
        spec_cache = [
            {
                "operation_id": "cancelOrder",
                "method": "POST",
                "path": "/orders/{orderId}/cancel",
                "summary": "Cancel an order",
                "input_schema": {
                    "type": "object",
                    "properties": {"orderId": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["orderId"],
                },
                "param_locations": {"orderId": "path", "reason": "body_field"},
            }
        ]
    config = {"spec_url": "https://storefront.example.com/openapi.json", "spec_cache": spec_cache}
    config.update(config_extra or {})
    integration = Integration(
        id="int_openapi_resolution_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Storefront API",
        type="openapi",
        base_url="https://storefront.example.com",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "t"}),
        config=config,
        enabled=True,
        created_by="staff_1",
    )
    await IntegrationRepository(db_session, DEFAULT_TENANT_ID).create(integration)


class _StubLLM:
    def __init__(self, selection: ExternalToolSelection) -> None:
        self._selection = selection

    async def generate(
        self, messages: list[LLMMessage], *, max_tokens: int = 1024, usage_callback=None
    ) -> str:
        raise NotImplementedError

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ):
        assert schema is ExternalToolSelection
        return self._selection


async def test_returns_none_when_no_integration_configured(mcp_ctx):
    stub_llm = _StubLLM(ExternalToolSelection(tool_index=0))
    result = await propose_external_tool_call(mcp_ctx, stub_llm, "where is my order")

    assert result is None


async def test_returns_none_when_model_declines(db_session, mcp_ctx, mcp_server_url):
    await _add_enabled_mcp_integration(db_session, mcp_server_url)

    result = await propose_external_tool_call(
        mcp_ctx, _StubLLM(ExternalToolSelection(tool_index=-1)), "what's the weather"
    )

    assert result is None


async def test_proposes_the_selected_mcp_tool_with_valid_arguments(db_session, mcp_ctx, mcp_server_url):
    await _add_enabled_mcp_integration(db_session, mcp_server_url)
    selection = ExternalToolSelection(tool_index=0, arguments={"order_id": "order_1001"})

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "which carrier has my order")

    assert proposal is not None
    assert proposal.source == "mcp"
    assert proposal.tool_name == "get_shipping_carrier"
    assert proposal.integration_name == "Shipping MCP"
    assert proposal.arguments == {"order_id": "order_1001"}
    assert proposal.method is None


async def test_rejects_arguments_that_fail_the_tools_schema(db_session, mcp_ctx, mcp_server_url):
    await _add_enabled_mcp_integration(db_session, mcp_server_url)
    # order_id is required by get_shipping_carrier's schema - omitting it
    # must not produce a proposal, even though the model "selected" a tool.
    selection = ExternalToolSelection(tool_index=0, arguments={})

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "which carrier has my order")

    assert proposal is None


async def test_out_of_range_tool_index_returns_none(db_session, mcp_ctx, mcp_server_url):
    await _add_enabled_mcp_integration(db_session, mcp_server_url)
    selection = ExternalToolSelection(tool_index=99, arguments={})

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "anything")

    assert proposal is None


async def test_proposes_the_selected_openapi_operation_with_valid_arguments(db_session, mcp_ctx):
    await _add_enabled_openapi_integration(db_session)
    selection = ExternalToolSelection(
        tool_index=0, arguments={"orderId": "order_1001", "reason": "changed mind"}
    )

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "cancel my order")

    assert proposal is not None
    assert proposal.source == "openapi"
    assert proposal.tool_name == "cancelOrder"
    assert proposal.integration_name == "Storefront API"
    assert proposal.method == "POST"
    assert proposal.path == "/orders/{orderId}/cancel"
    assert proposal.param_locations == {"orderId": "path", "reason": "body_field"}


async def test_openapi_rejects_arguments_missing_required_field(db_session, mcp_ctx):
    await _add_enabled_openapi_integration(db_session)
    # orderId is required - omitting it must not produce a proposal.
    selection = ExternalToolSelection(tool_index=0, arguments={"reason": "changed mind"})

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "cancel my order")

    assert proposal is None


async def test_catalog_merges_mcp_and_openapi_into_one_selection(db_session, mcp_ctx, mcp_server_url):
    """The core Phase 7 unification: both sources appear in the SAME
    numbered menu for a single LLM call - selecting index 1 (the second
    entry, discovery order: mcp first then openapi per _discover_catalog)
    must resolve to the openapi entry, not silently drop it."""
    await _add_enabled_mcp_integration(db_session, mcp_server_url)
    await _add_enabled_openapi_integration(db_session)
    selection = ExternalToolSelection(tool_index=1, arguments={"orderId": "order_1001"})

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "cancel my order")

    assert proposal is not None
    assert proposal.source == "openapi"
    assert proposal.tool_name == "cancelOrder"


def test_describe_arguments_names_each_property_and_required_flag():
    # Regression test: showing only a tool's name+description (the
    # original prompt) left the LLM guessing the actual argument key from
    # prose - live testing with a real Gemini call against DeepWiki's
    # `ask_question` tool showed it repeatedly invent plausible-but-wrong
    # keys (`repo_name`, `repo_url` instead of the schema's `repoName`),
    # which jsonschema validation correctly rejected every time but meant
    # the tool was never actually usable. Spelling out the exact name
    # closes that gap.
    schema = {
        "properties": {
            "repoName": {"type": "string", "description": "..."},
            "question": {"type": "string", "description": "..."},
        },
        "required": ["repoName", "question"],
    }

    assert _describe_arguments(schema) == "repoName: string (required), question: string (required)"


def test_describe_arguments_marks_optional_fields():
    schema = {
        "properties": {"limit": {"type": "integer"}},
        "required": [],
    }

    assert _describe_arguments(schema) == "limit: integer (optional)"


def test_describe_arguments_handles_no_properties():
    assert _describe_arguments({"properties": {}, "required": []}) == "(none)"


# --- Phase 7 A2: role filtering + is_mutating computation ---


async def test_role_filter_excludes_integrations_without_matching_role(db_session, mcp_ctx, mcp_server_url):
    # No integration is tagged role="storefront" - the storefront-only
    # catalog must come back empty even though a plain mcp integration exists.
    await _add_enabled_mcp_integration(db_session, mcp_server_url)

    catalog = await _discover_catalog(mcp_ctx, role="storefront")

    assert catalog == []


async def test_role_filter_includes_only_matching_integration(db_session, mcp_ctx, mcp_server_url):
    await _add_enabled_mcp_integration(db_session, mcp_server_url)
    await _add_enabled_openapi_integration(db_session, config_extra={"role": "storefront"})

    catalog = await _discover_catalog(mcp_ctx, role="storefront")

    assert len(catalog) == 1
    assert catalog[0].source == "openapi"
    assert catalog[0].integration_name == "Storefront API"


async def test_role_none_returns_every_enabled_integration_regardless_of_role(
    db_session, mcp_ctx, mcp_server_url
):
    await _add_enabled_mcp_integration(db_session, mcp_server_url)
    await _add_enabled_openapi_integration(db_session, config_extra={"role": "storefront"})

    catalog = await _discover_catalog(mcp_ctx, role=None)

    assert {entry.source for entry in catalog} == {"mcp", "openapi"}


async def test_openapi_get_operation_is_not_mutating(db_session, mcp_ctx):
    spec_cache = [
        {
            "operation_id": "getOrder",
            "method": "GET",
            "path": "/orders/{orderId}",
            "summary": "Fetch an order",
            "input_schema": {
                "type": "object",
                "properties": {"orderId": {"type": "string"}},
                "required": ["orderId"],
            },
            "param_locations": {"orderId": "path"},
        }
    ]
    await _add_enabled_openapi_integration(db_session, spec_cache=spec_cache)

    catalog = await _discover_catalog(mcp_ctx, role=None)

    assert len(catalog) == 1
    assert catalog[0].is_mutating is False


async def test_openapi_post_operation_is_mutating(db_session, mcp_ctx):
    # _add_enabled_openapi_integration's default fixture spec is a POST
    # cancelOrder operation.
    await _add_enabled_openapi_integration(db_session)

    catalog = await _discover_catalog(mcp_ctx, role=None)

    assert len(catalog) == 1
    assert catalog[0].is_mutating is True


async def test_mcp_entries_always_default_to_mutating(db_session, mcp_ctx, mcp_server_url):
    # MCP has no structural read/write signal (see CatalogEntry.is_mutating's
    # docstring) - every MCP-sourced entry must be treated as mutating,
    # regardless of what the tool is actually named.
    await _add_enabled_mcp_integration(db_session, mcp_server_url)

    catalog = await _discover_catalog(mcp_ctx, role=None)

    assert len(catalog) == 1
    assert catalog[0].is_mutating is True


# --- Phase 11 live-testing finding: PII-placeholder substitution ---
# app.workflow.nodes.resolve_issue redacts the customer's message before
# any LLM ever sees it, so the LLM can only ever propose the literal
# placeholder (e.g. "<EMAIL_REDACTED>") for an argument like "email" - a
# real external API verifying identity by order ID + email then rejects
# the call outright (live-verified against a real connected backend).
# propose_external_tool_call substitutes the real value from this app's
# own Customer record afterward, so the LLM itself never sees raw PII.

_EMAIL_SPEC = [
    {
        "operation_id": "trackOrder",
        "method": "POST",
        "path": "/orders/track",
        "summary": "Look up an order by id and email",
        "input_schema": {
            "type": "object",
            "properties": {"orderId": {"type": "string"}, "email": {"type": "string"}},
            "required": ["orderId", "email"],
        },
        "param_locations": {"orderId": "body_field", "email": "body_field"},
    }
]


async def test_substitutes_the_real_customer_email_for_the_redaction_placeholder(
    db_session, seeded_customer
):
    await _add_enabled_openapi_integration(db_session, spec_cache=_EMAIL_SPEC)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id="wf_1",
        tenant_id=DEFAULT_TENANT_ID,
    )
    selection = ExternalToolSelection(
        tool_index=0, arguments={"orderId": "ORD-1", "email": "<EMAIL_REDACTED>"}
    )

    proposal = await propose_external_tool_call(ctx, _StubLLM(selection), "where is my order")

    assert proposal is not None
    assert proposal.arguments["email"] == f"{seeded_customer['customer_id']}@example.com"
    assert proposal.arguments["orderId"] == "ORD-1"


async def test_leaves_a_non_placeholder_value_unchanged(db_session, seeded_customer):
    await _add_enabled_openapi_integration(db_session, spec_cache=_EMAIL_SPEC)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id="wf_1",
        tenant_id=DEFAULT_TENANT_ID,
    )
    # The LLM occasionally sees a real value anyway (e.g. it was never
    # redacted because the customer typed it differently than the regex
    # expects) - substitution must never override a real, already-correct
    # value with the account's own email.
    selection = ExternalToolSelection(
        tool_index=0, arguments={"orderId": "ORD-1", "email": "someone-else@example.com"}
    )

    proposal = await propose_external_tool_call(ctx, _StubLLM(selection), "where is my order")

    assert proposal is not None
    assert proposal.arguments["email"] == "someone-else@example.com"


async def test_unknown_placeholder_is_left_as_is(db_session, seeded_customer):
    # <PHONE_REDACTED> has no corresponding Customer field (this model
    # doesn't store a phone number) - it must be left exactly as the LLM
    # proposed it, not guessed at, so this fails validation/execution the
    # same honest way it did before this fix existed.
    spec = [
        {
            **_EMAIL_SPEC[0],
            "input_schema": {
                "type": "object",
                "properties": {"orderId": {"type": "string"}, "phone": {"type": "string"}},
                "required": ["orderId", "phone"],
            },
        }
    ]
    await _add_enabled_openapi_integration(db_session, spec_cache=spec)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id="wf_1",
        tenant_id=DEFAULT_TENANT_ID,
    )
    selection = ExternalToolSelection(
        tool_index=0, arguments={"orderId": "ORD-1", "phone": "<PHONE_REDACTED>"}
    )

    proposal = await propose_external_tool_call(ctx, _StubLLM(selection), "where is my order")

    assert proposal is not None
    assert proposal.arguments["phone"] == "<PHONE_REDACTED>"


async def test_substitutes_a_bare_redacted_value_using_the_argument_key(db_session, seeded_customer):
    # Regression: live scenario testing caught the LLM collapsing
    # "<EMAIL_REDACTED>" down to a bare "REDACTED" (no angle brackets, no
    # type prefix) when the customer's message contained two emails (one
    # a self-correction) - the original exact-string match missed this
    # entirely and let the literal word "REDACTED" reach the real API.
    await _add_enabled_openapi_integration(db_session, spec_cache=_EMAIL_SPEC)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id="wf_1",
        tenant_id=DEFAULT_TENANT_ID,
    )
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "ORD-1", "email": "REDACTED"})

    proposal = await propose_external_tool_call(ctx, _StubLLM(selection), "where is my order")

    assert proposal is not None
    assert proposal.arguments["email"] == f"{seeded_customer['customer_id']}@example.com"


async def test_bare_redacted_for_an_unmapped_key_is_left_as_is(db_session, seeded_customer):
    # The key-name fallback only covers a fixed, known vocabulary - a bare
    # "REDACTED" for a field this app has no Customer attribute for (e.g.
    # "phone") must not be guessed at either.
    spec = [
        {
            **_EMAIL_SPEC[0],
            "input_schema": {
                "type": "object",
                "properties": {"orderId": {"type": "string"}, "phone": {"type": "string"}},
                "required": ["orderId", "phone"],
            },
        }
    ]
    await _add_enabled_openapi_integration(db_session, spec_cache=spec)
    ctx = ToolContext(
        session=db_session,
        requesting_customer_id=seeded_customer["customer_id"],
        workflow_run_id="wf_1",
        tenant_id=DEFAULT_TENANT_ID,
    )
    selection = ExternalToolSelection(tool_index=0, arguments={"orderId": "ORD-1", "phone": "REDACTED"})

    proposal = await propose_external_tool_call(ctx, _StubLLM(selection), "where is my order")

    assert proposal is not None
    assert proposal.arguments["phone"] == "REDACTED"


async def test_no_db_lookup_when_no_placeholder_is_present(db_session, mcp_ctx):
    # Fast path: a fabricated "cust_1" (mcp_ctx's own id, no real Customer
    # row) must not blow up with a lookup failure when nothing needs
    # substituting - proves the DB round-trip is genuinely skipped, not
    # just coincidentally successful.
    await _add_enabled_openapi_integration(db_session, spec_cache=_EMAIL_SPEC)
    selection = ExternalToolSelection(
        tool_index=0, arguments={"orderId": "ORD-1", "email": "real@example.com"}
    )

    proposal = await propose_external_tool_call(mcp_ctx, _StubLLM(selection), "where is my order")

    assert proposal is not None
    assert proposal.arguments["email"] == "real@example.com"
