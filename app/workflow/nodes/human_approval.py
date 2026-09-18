"""human_approval_gate node (spec §18): LangGraph interrupt-based human
approval for high-risk actions (refunds, and - spec: Phase 6, generalized
in Phase 7 - proposed external MCP/OpenAPI tool calls).

When `state["awaiting_approval"]` is set (by resolve_issue, via either
app.agents.resolution.resolve_refund or app.agents.external_tools's
fallback), this node calls `interrupt()`, which pauses graph execution and
persists the pause in the checkpointer - not an in-memory flag, so it
survives process restarts. The API layer's `POST /tickets/{id}/approve|reject`
endpoints resume the graph by invoking it again with
`Command(resume={"approved": bool})` against the same thread_id (see
app.api.routes.tickets).

For a refund, the state-changing work already happened before this gate
(create_refund_request already inserted the pending RefundRequest row) -
approval here just changes the ticket's status. An external tool call is
different: `state["pending_mcp_call"]` (field name kept for checkpoint
backward-compatibility - see app.agents.resolution's comment) names a
tool that has NOT run yet (app.agents.external_tools never executes one,
only proposes it), because neither an MCP server's nor an external REST
API's real-world side effects are reviewed code the way this codebase's
built-in tools are. The actual call only happens here, dispatched on
`pending_mcp["source"]` (`"mcp"` or `"openapi"`), and only once, after
approval - never speculatively.
"""

from __future__ import annotations

from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.domain.exceptions import IntegrationError
from app.integrations.mcp_client import call_tool as mcp_call_tool
from app.integrations.openapi_client import OpenApiOperationSpec
from app.integrations.openapi_client import call_operation as openapi_call_operation
from app.integrations.stripe import StripeClient
from app.observability.logging import get_logger
from app.repositories.integrations import IntegrationRepository
from app.repositories.orders import PaymentRepository, RefundRepository
from app.workflow.deps import get_deps
from app.workflow.state import SupportState

logger = get_logger(__name__)


async def _issue_stripe_refund(state: SupportState, config: RunnableConfig, refund: Any) -> dict:
    """spec: Phase 9.4b - if this tenant has a `stripe` integration
    enabled AND the refunded order's most recent `Payment` carries a
    `gateway_payment_intent_id`, actually issue the refund through
    Stripe. Neither condition holding means this app's pre-existing
    pure-DB simulation (the refund is "approved" in this app's own
    records) is the full extent of what "approved" means - the common
    case in this environment today, since no real Stripe account is
    connected. Real Stripe refunds are asynchronously confirmed - the
    webhook (app.api.routes.webhooks) is the authoritative "did this
    actually complete" signal, not this synchronous call, so success
    here only records a `gateway_reference`, it does not change
    `refund.status` again."""
    deps = get_deps(config)
    tenant_id = state["tenant_id"]
    stripe_integration = await IntegrationRepository(deps.session, tenant_id).get_enabled_by_type("stripe")
    if stripe_integration is None:
        return {}

    payment = await PaymentRepository(deps.session, tenant_id).get_latest_for_order(refund.order_id)
    if payment is None or not payment.gateway_payment_intent_id:
        return {}

    facts = list(state.get("resolution_facts", []))
    try:
        result = await StripeClient(stripe_integration).create_refund(
            payment_intent_id=payment.gateway_payment_intent_id,
            amount=refund.amount,
            reason=refund.reason,
        )
    except IntegrationError as exc:
        logger.warning("stripe_refund_failed", refund_id=refund.id, error=str(exc))
        facts.append(f"The refund was approved, but issuing it through Stripe failed: {exc}")
        return {
            "requires_human": True,
            "escalation_reason": f"Stripe refund failed after approval: {exc}",
            "resolution_facts": facts,
            "draft_response": (
                "Your refund was approved, but we hit an issue actually processing it. "
                "A team member will follow up."
            ),
        }

    refund.gateway = "stripe"
    refund.gateway_reference = result.get("id")
    await deps.session.flush()
    facts.append(f"Refund issued through Stripe (reference {refund.gateway_reference}).")
    return {"resolution_facts": facts}


async def _update_refund_status_after_decision(
    state: SupportState, config: RunnableConfig, *, approved: bool
) -> dict:
    """spec: Phase 9.4a - fixes a real, previously-unnoticed bug: nothing
    anywhere in this codebase ever flipped `RefundRequest.status` away
    from `"pending"` after a refund ticket was approved/rejected - only
    the ticket's own status field was ever updated. Finds the refund
    created earlier in this same run via `state["tool_results"]`
    (`app.agents.resolution.resolve_refund` appends a
    `{"tool": "create_refund_request", "result": {"refund_id": ..., ...}}`
    entry there - see RefundRequestResult), rather than needing a new way
    to pass the id through `interrupt()`/`Command.resume`. On approval
    only, also attempts a real gateway refund - see `_issue_stripe_refund`."""
    refund_id: str | None = None
    for tool_result in state.get("tool_results", []):
        if tool_result.get("tool") == "create_refund_request":
            refund_id = tool_result.get("result", {}).get("refund_id")
            break
    if refund_id is None:
        # Nothing to update - not every awaiting_approval run is a refund
        # (external-tool proposals never reach this branch, since the
        # caller only invokes this when pending_mcp is falsy, but a
        # defensively-missing tool_results entry shouldn't crash the resume).
        return {}

    deps = get_deps(config)
    refund_repo = RefundRepository(deps.session, state["tenant_id"])
    refund = await refund_repo.get(refund_id)
    if refund is None:
        logger.warning("refund_not_found_after_approval_decision", refund_id=refund_id)
        return {}
    await refund_repo.update_status(refund, "approved" if approved else "rejected")
    if not approved:
        return {}
    return await _issue_stripe_refund(state, config, refund)


async def human_approval_gate(state: SupportState, config: RunnableConfig) -> dict:
    if not state.get("awaiting_approval"):
        return {"approved": True}

    pending_mcp = state.get("pending_mcp_call")
    payload = {
        "type": "mcp_tool_approval" if pending_mcp else "refund_approval",
        "conversation_id": state["conversation_id"],
        "customer_id": state["customer_id"],
        "intent": state.get("intent"),
        "facts": state.get("resolution_facts", []),
    }
    if pending_mcp:
        payload["integration_name"] = pending_mcp["integration_name"]
        payload["tool_name"] = pending_mcp["tool_name"]
        payload["arguments"] = pending_mcp["arguments"]

    decision = interrupt(payload)
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    # spec: Phase 8.2 - staff-edited argument overrides from the ticket
    # review UI. Meaningless without a pending_mcp to merge into (a
    # refund resume never carries this key) - see
    # _execute_approved_external_call for the merge + re-validation.
    arguments_override = decision.get("arguments_override") if isinstance(decision, dict) else None

    update: dict = {"awaiting_approval": False, "approved": approved}
    if not approved:
        update["requires_human"] = True
        update["escalation_reason"] = state.get("escalation_reason") or (
            "External tool call rejected by human approver; needs manual follow-up"
            if pending_mcp
            else "Refund rejected by human approver; needs manual follow-up"
        )
        if not pending_mcp:
            await _update_refund_status_after_decision(state, config, approved=False)
        return update

    if pending_mcp:
        update.update(await _execute_approved_external_call(state, config, pending_mcp, arguments_override))
    else:
        update.update(await _update_refund_status_after_decision(state, config, approved=True))
    return update


async def _call_external_tool(integration: Any, pending_mcp: dict) -> dict[str, Any]:
    """Dispatches to the real MCP or OpenAPI call based on
    `pending_mcp["source"]` - defaults to `"mcp"` for any proposal that
    predates this key existing (checkpoint backward-compatibility)."""
    if pending_mcp.get("source", "mcp") == "openapi":
        op = OpenApiOperationSpec(
            operation_id=pending_mcp["tool_name"],
            method=pending_mcp["method"],
            path=pending_mcp["path"],
            summary="",
            input_schema={},
            param_locations=pending_mcp["param_locations"] or {},
        )
        return await openapi_call_operation(integration, op, pending_mcp["arguments"])
    result = await mcp_call_tool(integration, pending_mcp["tool_name"], pending_mcp["arguments"])
    return {"text": result["text"]}


def _result_text(source: str, result: dict[str, Any]) -> str:
    if source == "openapi":
        return str(result.get("result", "completed with no output"))
    return result.get("text") or "completed with no output"


async def _execute_approved_external_call(
    state: SupportState,
    config: RunnableConfig,
    pending_mcp: dict,
    arguments_override: dict[str, Any] | None = None,
) -> dict:
    deps = get_deps(config)
    source = pending_mcp.get("source", "mcp")
    facts = list(state.get("resolution_facts", []))
    integration = await IntegrationRepository(deps.session, state["tenant_id"]).get(
        pending_mcp["integration_id"]
    )
    if integration is None or not integration.enabled:
        facts.append(f"The connected '{pending_mcp['integration_name']}' tool is no longer available.")
        return {
            "requires_human": True,
            "escalation_reason": "The connected integration was removed or disabled after approval",
            "resolution_facts": facts,
            "draft_response": (
                "I'm sorry, I wasn't able to complete that - the connected tool is no longer "
                "available. A team member will follow up."
            ),
        }

    # spec: Phase 8.2 - a staff-edited argument override from the ticket
    # review UI, shallow-merged so staff only need to send the fields
    # they actually changed. Re-validated against the same JSON Schema
    # propose_external_tool_call already checked the original,
    # LLM-proposed arguments against - an override bypassing that check
    # entirely would be a real regression, not just an omission.
    if arguments_override:
        merged_arguments = {**pending_mcp["arguments"], **arguments_override}
        input_schema = pending_mcp.get("input_schema") or {}
        try:
            jsonschema_validate(instance=merged_arguments, schema=input_schema)
        except JsonSchemaValidationError as exc:
            logger.warning(
                "external_tool_argument_override_invalid",
                integration_id=pending_mcp["integration_id"],
                source=source,
                tool=pending_mcp["tool_name"],
                error=str(exc),
            )
            tool_name = pending_mcp["tool_name"]
            facts.append(f"The edited arguments for '{tool_name}' failed validation: {exc.message}")
            return {
                "requires_human": True,
                "escalation_reason": f"Staff-edited arguments failed schema validation: {exc.message}",
                "resolution_facts": facts,
                "draft_response": (
                    "I'm sorry, I wasn't able to complete that - the edited request wasn't valid. "
                    "A team member will follow up."
                ),
            }
        pending_mcp = {**pending_mcp, "arguments": merged_arguments}

    try:
        result = await _call_external_tool(integration, pending_mcp)
    except IntegrationError as exc:
        logger.warning(
            "external_tool_approved_call_failed",
            integration_id=integration.id,
            source=source,
            tool=pending_mcp["tool_name"],
            error=str(exc),
        )
        facts.append(
            f"Calling '{pending_mcp['tool_name']}' via {pending_mcp['integration_name']} failed: {exc}"
        )
        return {
            "requires_human": True,
            "escalation_reason": f"External tool call failed after approval: {exc}",
            "resolution_facts": facts,
            "draft_response": (
                "I attempted to complete that using a connected tool, but it failed. A team "
                "member will follow up."
            ),
            "execution_result": {"error": str(exc)},
        }

    result_text = _result_text(source, result)
    facts.append(f"Called '{pending_mcp['tool_name']}' via {pending_mcp['integration_name']}: {result_text}")
    return {
        "resolution_facts": facts,
        "draft_response": (
            f"I checked using our connected {pending_mcp['integration_name']} integration: {result_text}"
        ),
        "execution_result": result,
    }
