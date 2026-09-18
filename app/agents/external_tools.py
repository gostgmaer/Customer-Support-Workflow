"""External tool-selection fallback (spec: Phase 6 MCP integration, Phase 7
generalized to also cover OpenAPI/Swagger-described REST APIs).

Consulted from two call sites in app.agents.resolution: as a last resort
in gather_resolution_facts (when the intent has no deterministic resolver
and knowledge-base retrieval came up empty), and - spec: Phase 7 A2 -
as the *primary* path for commerce-shaped intents when the tenant has a
`config.role == "storefront"` integration connected
(resolve_via_storefront). Either way this keeps rule 17 ("prefer
deterministic business logic over autonomous LLM decisions") intact: the
LLM never gets to override a resolver that already knows what to do
(storefront routing only replaces resolvers for tenants that explicitly
connected a storefront), it only narrows a small, admin-configured menu
of externally connected tools.

MCP-sourced tools and OpenAPI-sourced operations are merged into ONE
catalog for a single LLM selection call, rather than trying MCP then
OpenAPI sequentially - this halves the LLM calls a fallback costs and
gives the model the full picture of what's actually connected at once.

Selecting a tool never runs it by itself. Every external tool call is
treated as high-risk regardless of source or HTTP method and requires
human approval (`app.workflow.nodes.human_approval`, the same gate used
for refunds) - unlike this codebase's built-in tools, neither an MCP
server's nor an external REST API's actual behavior is reviewed code. The
ONE exception: a read-only OpenAPI operation (GET/HEAD) proposed via
storefront routing executes immediately, without a ticket, if that
integration has explicitly opted into `config.auto_execute_reads` - see
`execute_proposal` and `app.agents.resolution.resolve_via_storefront`.
MCP tools are never eligible for this (see `CatalogEntry.is_mutating`'s
docstring for why), and a mutating OpenAPI operation never is either
regardless of the flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate

from app.agents.schemas import ExternalToolSelection
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.mcp_client import call_tool as mcp_call_tool
from app.integrations.mcp_client import list_tools as mcp_list_tools
from app.integrations.openapi_client import OpenApiOperationSpec
from app.integrations.openapi_client import call_operation as openapi_call_operation
from app.integrations.openapi_client import list_operations as openapi_list_operations
from app.llm.base import LLMProvider
from app.observability.logging import get_logger
from app.repositories.integrations import IntegrationRepository
from app.security.prompt_security import build_prompt_messages
from app.tools.base import ToolContext

logger = get_logger(__name__)

_SELECTION_RULES = (
    "You may propose calling AT MOST ONE of the following externally connected "
    "tools, and only if it would directly help answer the customer's message. "
    "Set tool_index to -1 if none of them apply - do not guess. Use each "
    "argument's exact name as listed under 'arguments:' for that tool - do not "
    "rename, abbreviate, or reformat it. Never invent argument values that "
    "aren't derivable from the customer's message; omit an argument you're not "
    "confident about rather than fabricate one."
)


@dataclass
class CatalogEntry:
    integration_id: str
    integration_name: str
    source: Literal["mcp", "openapi"]
    name: str  # MCP tool name, or OpenAPI operationId
    description: str
    input_schema: dict[str, Any]
    # OpenAPI-only, needed to reconstruct the call at approval time (the
    # LangGraph checkpointer only persists plain JSON-safe state, not the
    # live OpenApiOperationSpec object) - unused/None for MCP entries.
    method: str | None = None
    path: str | None = None
    param_locations: dict[str, str] | None = None
    # Read-only OpenAPI operations (GET/HEAD) can be auto-executed by a
    # storefront-routed proposal (spec: Phase 7 A2) when the integration
    # opts into `config.auto_execute_reads` - MCP entries default True
    # (always treated as mutating) because the protocol has no structural
    # read/write signal the way an HTTP method does; a tool named
    # "get_status" could still mutate state server-side and there's no
    # reliable way to know from here.
    is_mutating: bool = True


def _describe_arguments(input_schema: dict[str, Any]) -> str:
    """Renders a tool's exact argument names (spelling and casing as the
    server/spec defines them) into the selection prompt. Showing only
    name+description (the original version of this prompt) left the model
    guessing the actual key name from prose - in live testing, real
    Gemini repeatedly invented plausible-but-wrong keys for DeepWiki's
    `ask_question` tool (`repo_name`, then `repo_url`, instead of the
    schema's `repoName`), which jsonschema validation correctly rejected
    every time (see propose_external_tool_call) but meant the tool was
    never actually usable in practice. Spelling out each argument's exact
    name and type up front gives the model far less room to guess wrong."""
    properties = input_schema.get("properties", {})
    if not properties:
        return "(none)"
    required = set(input_schema.get("required", []))
    parts = []
    for name, spec in properties.items():
        type_hint = spec.get("type") or "any"
        marker = "required" if name in required else "optional"
        parts.append(f"{name}: {type_hint} ({marker})")
    return ", ".join(parts)


async def _discover_mcp_entries(ctx: ToolContext, integrations: list[Integration]) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for integration in integrations:
        try:
            tools = await mcp_list_tools(integration)
        except IntegrationError as exc:
            logger.warning("mcp_list_tools_failed", integration_id=integration.id, error=str(exc))
            continue
        entries.extend(
            CatalogEntry(
                integration_id=integration.id,
                integration_name=integration.name,
                source="mcp",
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in tools
        )
    return entries


async def _discover_openapi_entries(ctx: ToolContext, integrations: list[Integration]) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for integration in integrations:
        try:
            operations = await openapi_list_operations(integration)
        except IntegrationError as exc:
            logger.warning("openapi_list_operations_failed", integration_id=integration.id, error=str(exc))
            continue
        entries.extend(
            CatalogEntry(
                integration_id=integration.id,
                integration_name=integration.name,
                source="openapi",
                name=op.operation_id,
                description=op.summary,
                input_schema=op.input_schema,
                method=op.method,
                path=op.path,
                param_locations=op.param_locations,
                is_mutating=op.method not in ("GET", "HEAD"),
            )
            for op in operations
        )
    return entries


async def _discover_catalog(ctx: ToolContext, *, role: str | None = None) -> list[CatalogEntry]:
    """Every enabled MCP + OpenAPI integration for this tenant, merged into
    one catalog. A single integration being unreachable/misconfigured is
    logged and skipped, not fatal - other connected integrations (and the
    normal escalation path) should still work.

    `role` filters to integrations tagged `config.role == role` (spec:
    Phase 7 A2 - storefront-primary commerce routing passes
    `role="storefront"` so the catalog only offers that tenant's
    designated storefront, not every unrelated MCP/OpenAPI integration
    they've connected for other purposes). `None` (the default, used by
    the general last-resort fallback) means every enabled integration
    regardless of role."""
    repo = IntegrationRepository(ctx.session, ctx.tenant_id)
    mcp_integrations = await repo.list_enabled_by_type("mcp")
    openapi_integrations = await repo.list_enabled_by_type("openapi")
    if role is not None:
        mcp_integrations = [i for i in mcp_integrations if i.config.get("role") == role]
        openapi_integrations = [i for i in openapi_integrations if i.config.get("role") == role]
    mcp_entries = await _discover_mcp_entries(ctx, mcp_integrations)
    openapi_entries = await _discover_openapi_entries(ctx, openapi_integrations)
    return mcp_entries + openapi_entries


class ExternalToolProposal:
    def __init__(
        self,
        *,
        integration_id: str,
        integration_name: str,
        source: Literal["mcp", "openapi"],
        tool_name: str,
        arguments: dict[str, Any],
        method: str | None = None,
        path: str | None = None,
        param_locations: dict[str, str] | None = None,
        is_mutating: bool = True,
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        self.integration_id = integration_id
        self.integration_name = integration_name
        self.source = source
        self.tool_name = tool_name
        self.arguments = arguments
        self.method = method
        self.path = path
        self.param_locations = param_locations
        self.is_mutating = is_mutating
        # spec: Phase 8.2 - carried so a staff-edited argument override at
        # approval time can be re-validated against the same schema
        # `propose_external_tool_call` already checked the original,
        # LLM-proposed arguments against below, rather than letting an
        # override bypass validation entirely.
        self.input_schema = input_schema or {}


async def propose_external_tool_call(
    ctx: ToolContext, llm: LLMProvider, message: str, *, role: str | None = None
) -> ExternalToolProposal | None:
    """Returns a proposed (not yet executed) tool call, or None if this
    tenant has no enabled MCP/OpenAPI integration (matching `role`, if
    given), every connected one is unreachable, or the model found
    nothing suitable. The caller (app.agents.resolution.resolve_from_knowledge's
    fallback, or resolve_via_storefront's commerce routing) treats None
    exactly like "no answer found" - the normal escalation path."""
    catalog = await _discover_catalog(ctx, role=role)
    if not catalog:
        return None

    tool_lines = "\n".join(
        f'{i}. integration="{entry.integration_name}" tool="{entry.name}" - '
        f'{entry.description or "no description"}\n'
        f"   arguments: {_describe_arguments(entry.input_schema)}"
        for i, entry in enumerate(catalog)
    )
    messages = build_prompt_messages(
        business_policies="",
        developer_rules=f"{_SELECTION_RULES}\n\nAVAILABLE TOOLS:\n{tool_lines}",
        retrieved_knowledge=[],
        customer_message=message,
    )
    selection = await llm.generate_structured(messages, schema=ExternalToolSelection)
    if not (0 <= selection.tool_index < len(catalog)):
        return None

    entry = catalog[selection.tool_index]
    try:
        jsonschema_validate(instance=selection.arguments, schema=entry.input_schema)
    except JsonSchemaValidationError as exc:
        logger.warning(
            "external_tool_argument_validation_failed",
            integration_id=entry.integration_id,
            source=entry.source,
            tool=entry.name,
            error=str(exc),
        )
        return None

    return ExternalToolProposal(
        integration_id=entry.integration_id,
        integration_name=entry.integration_name,
        source=entry.source,
        tool_name=entry.name,
        arguments=selection.arguments,
        method=entry.method,
        path=entry.path,
        param_locations=entry.param_locations,
        is_mutating=entry.is_mutating,
        input_schema=entry.input_schema,
    )


async def execute_proposal(integration: Integration, proposal: ExternalToolProposal) -> dict[str, Any]:
    """The actual external call - MCP or OpenAPI, dispatched by
    `proposal.source`. Called from exactly two places: `app.workflow.nodes.human_approval`
    after staff approval (the default, safety-first path for every
    proposal), and `app.agents.resolution.resolve_via_storefront` for a
    read-only OpenAPI proposal when the integration has explicitly opted
    into `config.auto_execute_reads` (spec: Phase 7 A2) - never anywhere
    else. Raises `IntegrationError` on failure, same contract as
    `mcp_client.call_tool`/`openapi_client.call_operation` individually."""
    if proposal.source == "openapi":
        op = OpenApiOperationSpec(
            operation_id=proposal.tool_name,
            method=proposal.method or "GET",
            path=proposal.path or "",
            summary="",
            input_schema={},
            param_locations=proposal.param_locations or {},
        )
        return await openapi_call_operation(integration, op, proposal.arguments)
    result = await mcp_call_tool(integration, proposal.tool_name, proposal.arguments)
    return {"text": result["text"]}
