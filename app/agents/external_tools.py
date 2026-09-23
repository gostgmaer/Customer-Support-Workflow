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

import re
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.repositories.customers import CustomerRepository
from app.repositories.integrations import IntegrationRepository
from app.security.prompt_security import build_prompt_messages
from app.tools.base import ToolContext

logger = get_logger(__name__)

# Redaction-placeholder -> Customer attribute this app can safely
# substitute back in (spec: Phase 11 live-testing finding - an external
# tool's schema can legitimately need PII as an argument, e.g. "verify by
# order ID + email", but app.workflow.nodes.resolve_issue redacts the
# customer's message before any LLM ever sees it - see app.security.pii.
# The LLM correctly proposes whichever placeholder it was shown; this
# substitutes the REAL value from this app's own customer record
# afterward, so the LLM itself never sees raw PII (no new exposure to the
# LLM provider or LangSmith tracing). Only covers fields this app
# actually stores (just `email` today - Customer has no phone/address) -
# anything else the LLM proposes a placeholder for is left as-is and
# fails validation/execution the same way it did before this fix, rather
# than guessing at a value this app has no record of.
#
# The LLM does not always echo the placeholder back verbatim - live
# scenario testing (a customer message containing two emails, one a
# self-correction) caught it collapsing "<EMAIL_REDACTED>" down to a bare
# "REDACTED", dropping both the angle brackets and the type prefix. The
# regex below accepts any of "<EMAIL_REDACTED>", "EMAIL_REDACTED", or a
# bare "REDACTED"; when the type prefix itself is missing, the argument's
# own key name (e.g. "email") is the fallback signal for which field to
# substitute - still a fixed, known vocabulary, never a fuzzy guess.
_REDACTED_VALUE_RE = re.compile(r"^<?\s*(?:([A-Za-z]+)_)?REDACTED\s*>?$", re.IGNORECASE)

_REDACTION_TYPE_TO_CUSTOMER_FIELD: dict[str, str] = {
    "EMAIL": "email",
}
_ARGUMENT_KEY_TO_CUSTOMER_FIELD: dict[str, str] = {
    "email": "email",
}


def _customer_field_for_placeholder(key: str, value: str) -> str | None:
    match = _REDACTED_VALUE_RE.match(value.strip())
    if not match:
        return None
    redaction_type = match.group(1)
    if redaction_type:
        return _REDACTION_TYPE_TO_CUSTOMER_FIELD.get(redaction_type.upper())
    return _ARGUMENT_KEY_TO_CUSTOMER_FIELD.get(key.lower())


async def _substitute_known_placeholders(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    candidates = {
        key: _customer_field_for_placeholder(key, value)
        for key, value in arguments.items()
        if isinstance(value, str)
    }
    if not any(candidates.values()):
        return arguments  # fast path - nothing to substitute, no DB round-trip needed

    customer = await CustomerRepository(ctx.session, ctx.tenant_id).get(ctx.requesting_customer_id)
    if customer is None:
        return arguments

    substituted = dict(arguments)
    for key, field in candidates.items():
        if field is None:
            continue
        real_value = getattr(customer, field, None)
        if real_value:
            substituted[key] = real_value
    return substituted

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
    arguments = await _substitute_known_placeholders(ctx, selection.arguments)
    try:
        jsonschema_validate(instance=arguments, schema=entry.input_schema)
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
        arguments=arguments,
        method=entry.method,
        path=entry.path,
        param_locations=entry.param_locations,
        is_mutating=entry.is_mutating,
        input_schema=entry.input_schema,
    )


async def execute_proposal(integration: Integration, proposal: ExternalToolProposal) -> dict[str, Any]:
    """The actual external call - MCP or OpenAPI, dispatched by
    `proposal.source`. Called from three places: `app.workflow.nodes.human_approval`
    after staff approval (the default, safety-first path for every
    proposal), `app.agents.resolution.resolve_via_storefront` for a
    read-only OpenAPI proposal when the integration has explicitly opted
    into `config.auto_execute_reads` (spec: Phase 7 A2), and
    `app.agents.resolution._lookup_order_snapshot_via_storefront` for a
    read-only order-status lookup that feeds the REFUND/RETURNS policy
    check (spec: Phase 12) - never for a mutating proposal outside the
    approval flow. Raises `IntegrationError` on failure, same contract as
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


# spec: Phase 14 - resource-ownership verification. Confirmed gap: nothing
# anywhere checked that an order/subscription/payment id an LLM extracted
# from a customer's own chat message actually BELONGED to that customer
# before proposing (mutating) or auto-executing (read) an external call
# with it - a customer typing a stranger's order id would have it acted on
# exactly the same as their own. This is deliberately best-effort and
# OpenAPI-only:
#
# - An MCP tool's resource shape is arbitrary per-server (no HTTP-method or
#   REST-path convention to exploit the way OpenAPI has), so there is no
#   generic way to find "the sibling read operation for this resource" or
#   trust a response shape enough to extract an owner field from it. This
#   is a named, undosed residual risk for `source == "mcp"` - see
#   docs/SECURITY.md's "Resource ownership verification" section.
# - For OpenAPI, verification only fires when (a) the proposed arguments
#   contain a value whose key names a known resource type (order/
#   subscription/payment/invoice/account), AND (b) the SAME integration's
#   already-cached spec exposes a GET operation addressing that same
#   resource type, AND (c) that read call succeeds and its response
#   contains a recognizable owner-identifying field (email/customer id/
#   customer name). Any of those three conditions failing means ownership
#   genuinely cannot be determined from what this integration exposes -
#   this fails OPEN (the action proceeds, a structured log records the gap)
#   rather than fail closed, a deliberate choice: refusing every action on
#   any integration that merely lacks a matching read operation (a common,
#   legitimate API shape - many real write-only webhooks/operations have no
#   read counterpart) would break large swaths of already-shipped,
#   live-verified storefront-routing functionality for no confirmed
#   problem, not just a hypothetical one - it would have broken EVERY
#   scenario against this project's own demo_storefront fixture before its
#   orders/payments/subscriptions were given a `customer_email` field
#   specifically to make this check meaningful (spec: Phase 14). A
#   CONFIRMED mismatch (the read succeeds and its owner field genuinely
#   doesn't match) is the one case that always fails closed.
_RESOURCE_ID_KEY_HINTS: tuple[tuple[str, str], ...] = (
    ("order", "order"),
    ("subscription", "subscription"),
    ("invoice", "invoice"),
    ("payment", "payment"),
    ("account", "account"),
)

_OWNER_KEY_HINTS = ("email", "customerid", "customerref", "customername", "accountemail")

# Some real operations (e.g. this project's own committed demo storefront's
# `getSubscription(customer_ref)`/`changeSubscriptionPlan(customer_ref)`)
# address a resource directly by a customer-identifying reference rather
# than by an opaque order/payment id - there is no separate resource to
# look up, the argument itself IS the ownership claim. Checked first, and
# takes priority over `_RESOURCE_ID_KEY_HINTS` below: it needs no read
# lookup at all (cheaper, and closes a real gap `_substitute_known_placeholders`
# doesn't - that mechanism only ever forces an `email`-named argument to
# the real customer's own email, never a `customer_ref`/`customer_id`-named
# one, so an LLM proposing e.g. `customer_ref: "CUST-bob"` while acting for
# a different authenticated customer previously sailed through unverified).
_DIRECT_CUSTOMER_KEY_HINTS = ("customerref", "customerid", "customeremail", "accountref")


def _extract_direct_customer_reference(arguments: dict[str, Any]) -> str | None:
    for key, value in arguments.items():
        if isinstance(value, str) and any(
            hint in key.lower().replace("_", "") for hint in _DIRECT_CUSTOMER_KEY_HINTS
        ):
            return value
    return None


def _extract_resource_identifier(arguments: dict[str, Any]) -> tuple[str, str] | None:
    """First string-valued argument whose key names a known resource type
    (e.g. `orderId`, `order_id`, `subscription_ref`) - generalizes
    `app.agents.resolution._extract_order_id_from_arguments` (kept there
    unchanged for its own narrower webhook-correlation use) to every
    resource type an external action might mutate, not just orders."""
    for key, value in arguments.items():
        if not isinstance(value, str):
            continue
        key_lower = key.lower()
        for hint, resource_type in _RESOURCE_ID_KEY_HINTS:
            if hint in key_lower:
                return resource_type, value
    return None


def _find_owner_value(obj: Any, *, _depth: int = 0) -> str | None:
    """Best-effort recursive scan of an arbitrary nested dict/list (an
    external storefront's own response shape, never controlled by this
    app) for a string value whose key suggests a customer-identifying
    field. Depth-capped defensively - an external response is untrusted
    shape/size. Mirrors `app.agents.resolution._find_first_string_value`'s
    own precedent, kept as a separate, self-contained copy here to avoid a
    cross-module dependency between the two agent modules for a ~10-line
    helper."""
    if _depth > 6:
        return None
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized_key = key.lower().replace("_", "")
            if isinstance(value, str) and any(hint in normalized_key for hint in _OWNER_KEY_HINTS):
                return value
        for value in obj.values():
            found = _find_owner_value(value, _depth=_depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_owner_value(item, _depth=_depth + 1)
            if found is not None:
                return found
    return None


def _find_read_operation_for_resource(integration: Integration, resource_type: str) -> dict[str, Any] | None:
    """Pure, local, no-network inspection of this integration's already-
    cached OpenAPI operation list (`config.spec_cache`, populated at
    connect/Test time - see app.integrations.health) for a GET operation
    whose path plausibly addresses the same resource type as the mutating
    call just proposed (e.g. a POST /orders/{id}/cancel implies a sibling
    GET /orders/{id}). Deliberately checked BEFORE any LLM/HTTP round trip
    is attempted, so an integration with no such operation costs nothing
    beyond a dict scan."""
    for op in integration.config.get("spec_cache") or []:
        if not isinstance(op, dict):
            continue
        if str(op.get("method", "")).upper() != "GET":
            continue
        path_params = [k for k, loc in (op.get("param_locations") or {}).items() if loc == "path"]
        if len(path_params) == 1 and resource_type in str(op.get("path", "")).lower():
            return op
    return None


def _normalize_for_comparison(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _owner_matches(owner_value: str, *, email: str, full_name: str, customer_id: str) -> bool:
    """Exact match on email is the reliable case (this app's own customer
    record is the source of truth `_substitute_known_placeholders` already
    trusts for it). A storefront-opaque customer reference (e.g. this
    project's own demo storefront's `"CUST-alice"`) has no guaranteed
    format this app controls, so that comparison is deliberately
    best-effort/fuzzy - normalized (lowercased, punctuation stripped) and
    checked as a substring either direction against the customer's id/
    full name, not just exact equality. This can't be made airtight
    without a real, universal customer-reference format to rely on -
    named as a residual risk in docs/SECURITY.md, not silently assumed
    precise."""
    owner_norm = _normalize_for_comparison(owner_value)
    if not owner_norm:
        return False
    if owner_norm == _normalize_for_comparison(email):
        return True
    for candidate in (full_name, customer_id):
        candidate_norm = _normalize_for_comparison(candidate)
        if not candidate_norm:
            continue
        if owner_norm == candidate_norm or owner_norm in candidate_norm or candidate_norm in owner_norm:
            return True
    return False


async def verify_resource_ownership(
    session: AsyncSession,
    *,
    tenant_id: str,
    requesting_customer_id: str,
    integration: Integration,
    source: Literal["mcp", "openapi"],
    arguments: dict[str, Any],
    prefetched_result: dict[str, Any] | None = None,
) -> bool:
    """Returns False only for a CONFIRMED cross-customer ownership
    mismatch - the caller must refuse the action (no ticket, no
    auto-execute, no post-approval dispatch) and never reveal that the
    resource exists. Returns True for a verified match AND for every
    "genuinely could not check" case (see module comment above for why
    that's the deliberate default, not an oversight).

    `prefetched_result` lets a caller that already fetched the resource
    for another reason (the auto-execute-read path already has its own
    result in hand) skip a second, redundant network round trip - the
    same response is scanned for an owner field instead of issuing a new
    GET."""
    if source != "mcp" and source != "openapi":
        return True
    if source == "mcp":
        logger.info("resource_ownership_unverifiable_mcp_source", tenant_id=tenant_id)
        return True

    direct_ref = _extract_direct_customer_reference(arguments)
    if direct_ref is not None:
        customer = await CustomerRepository(session, tenant_id).get(requesting_customer_id)
        if customer is None:
            return True
        if _owner_matches(
            direct_ref, email=customer.email, full_name=customer.full_name, customer_id=customer.id
        ):
            return True
        logger.warning(
            "resource_ownership_mismatch",
            tenant_id=tenant_id,
            requesting_customer_id=requesting_customer_id,
            integration_id=integration.id,
            resource_type="direct_customer_reference",
        )
        return False

    identifier = _extract_resource_identifier(arguments)
    if identifier is None:
        return True
    resource_type, id_value = identifier

    if prefetched_result is not None:
        result = prefetched_result
    else:
        read_op = _find_read_operation_for_resource(integration, resource_type)
        if read_op is None:
            logger.info(
                "resource_ownership_unverifiable_no_read_operation",
                tenant_id=tenant_id,
                integration_id=integration.id,
                resource_type=resource_type,
            )
            return True
        path_param = next(k for k, loc in (read_op.get("param_locations") or {}).items() if loc == "path")
        op = OpenApiOperationSpec(
            operation_id=str(read_op.get("operation_id", "")),
            method="GET",
            path=str(read_op.get("path", "")),
            summary="",
            input_schema={},
            param_locations=read_op.get("param_locations") or {},
        )
        try:
            result = await openapi_call_operation(integration, op, {path_param: id_value})
        except IntegrationError as exc:
            logger.info(
                "resource_ownership_check_lookup_failed",
                tenant_id=tenant_id,
                integration_id=integration.id,
                resource_type=resource_type,
                error=str(exc),
            )
            return True

    owner_value = _find_owner_value(result)
    if owner_value is None:
        logger.info(
            "resource_ownership_unverifiable_no_owner_field",
            tenant_id=tenant_id,
            integration_id=integration.id,
            resource_type=resource_type,
        )
        return True

    customer = await CustomerRepository(session, tenant_id).get(requesting_customer_id)
    if customer is None:
        return True
    if _owner_matches(
        owner_value, email=customer.email, full_name=customer.full_name, customer_id=customer.id
    ):
        return True

    logger.warning(
        "resource_ownership_mismatch",
        tenant_id=tenant_id,
        requesting_customer_id=requesting_customer_id,
        integration_id=integration.id,
        resource_type=resource_type,
    )
    return False
