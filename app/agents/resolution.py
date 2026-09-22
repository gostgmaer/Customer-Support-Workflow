"""Resolution agent (spec §13-14).

Deterministically maps intent -> which tool(s)/knowledge to consult (rule 17:
prefer deterministic business logic over autonomous LLM decisions), then
asks the LLM only to *phrase* a response from the facts gathered - it never
asks the LLM to decide what actions to take. The drafted response always
follows the "what I know / what I checked / what I changed / what I cannot
verify / what happens next" structure from §13.

Mutating actions (cancel, refund, subscription change) require the customer
to have explicitly confirmed in this turn - `needs_confirmation` detects
whether the previous assistant turn already asked and this turn affirms it.
High-risk actions (refunds) are always additionally routed to human approval
after being created, regardless of confirmation - see app.workflow.nodes.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agents.confirmation import customer_already_confirmed
from app.agents.external_tools import execute_proposal, propose_external_tool_call
from app.agents.policy_check import check_commerce_policy
from app.config.policies import get_tool_policy
from app.domain.exceptions import IntegrationError, ToolError
from app.domain.models import Integration
from app.llm.base import LLMProvider
from app.observability.logging import get_logger
from app.rag.retriever import RetrievedDocument, Retriever
from app.repositories.conversations import ConversationRepository
from app.repositories.integrations import IntegrationRepository
from app.security.prompt_security import build_prompt_messages
from app.services.idempotency import build_idempotency_key
from app.tools import customer as customer_tools
from app.tools import orders as order_tools
from app.tools import payments as payment_tools
from app.tools import refunds as refund_tools
from app.tools import subscriptions as subscription_tools
from app.tools.base import ToolContext, record_external_tool_execution

logger = get_logger(__name__)


@dataclass
class ResolutionOutcome:
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    pending_confirmation: bool = False
    requires_human: bool = False
    awaiting_approval: bool = False
    escalation_reason: str | None = None
    errors: list[dict] = field(default_factory=list)
    # Set only by the external-tool fallback (see resolve_from_knowledge)
    # alongside awaiting_approval=True - app.workflow.nodes.resolve_issue
    # copies this into SupportState so human_approval_gate knows which
    # integration/tool to actually call once (and only once) a staff
    # member approves it. Field name kept as `pending_mcp_call` (not
    # source-neutral) for checkpoint backward-compatibility - see
    # resolve_from_knowledge's comment.
    pending_mcp_call: dict | None = None


async def _handle_order_lookup(ctx: ToolContext, customer_id: str) -> tuple[dict | None, ResolutionOutcome]:
    outcome = ResolutionOutcome()
    try:
        result = await order_tools.get_order_history(
            ctx, order_tools.GetOrderHistoryArgs(customer_id=customer_id, limit=1)
        )
        outcome.tool_calls.append({"tool": "get_order_history", "args": {"customer_id": customer_id}})
        outcome.tool_results.append({"tool": "get_order_history", "result": result.model_dump()})
        if not result.orders:
            outcome.facts.append("No orders were found on this account.")
            return None, outcome
        return result.orders[0].model_dump(), outcome
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        return None, outcome


async def resolve_order_status(ctx: ToolContext, customer_id: str, **_) -> ResolutionOutcome:
    order, outcome = await _handle_order_lookup(ctx, customer_id)
    if order:
        shipping = await order_tools.get_shipping_status(
            ctx, order_tools.GetShippingStatusArgs(customer_id=customer_id, order_id=order["order_id"])
        )
        outcome.tool_calls.append({"tool": "get_shipping_status", "args": {"order_id": order["order_id"]}})
        outcome.tool_results.append({"tool": "get_shipping_status", "result": shipping.model_dump()})
        outcome.facts.append(
            f"Order {order['order_id']} ({order['product_name']}) is currently '{order['status']}'. "
            f"Carrier: {shipping.carrier or 'n/a'}, tracking: {shipping.tracking_number or 'n/a'}, "
            f"estimated delivery: {shipping.estimated_delivery or 'unknown'}."
        )
    return outcome


async def resolve_order_cancel(
    ctx: ToolContext, customer_id: str, *, confirmed: bool, **_
) -> ResolutionOutcome:
    """spec: Phase 12 audit - deliberately has NO app.agents.policy_check
    gate, unlike resolve_refund. `NON_CANCELLABLE_STATUSES`
    (app.tools.orders.cancel_order) already deterministically enforces
    exactly the rule the real seeded Shipping Policy states ("cancelled
    free of charge only while status is 'placed'"), on every call, with
    no possibility of being bypassed - confirmed by reading both before
    deciding this. Adding an LLM-mediated policy check on top would only
    add latency/cost/a new failure mode for zero additional safety, and
    could theoretically even contradict the deterministic check (an LLM
    misreading policy text). The gate exists only where no deterministic
    check existed before this phase - see resolve_refund."""
    order, outcome = await _handle_order_lookup(ctx, customer_id)
    if not order:
        return outcome
    if not confirmed:
        outcome.pending_confirmation = True
        outcome.facts.append(
            f"Found order {order['order_id']} ({order['product_name']}, status '{order['status']}'). "
            "Please confirm you would like to cancel this order."
        )
        return outcome
    try:
        result = await order_tools.cancel_order(
            ctx,
            order_tools.CancelOrderArgs(
                customer_id=customer_id, order_id=order["order_id"], customer_confirmed=True
            ),
        )
        outcome.tool_calls.append({"tool": "cancel_order", "args": {"order_id": order["order_id"]}})
        outcome.tool_results.append({"tool": "cancel_order", "result": result.model_dump()})
        outcome.requires_human = get_tool_policy("cancel_order").human_approval.value == "always"
        if result.cancelled:
            outcome.facts.append(f"Order {order['order_id']} has been cancelled.")
        else:
            outcome.facts.append(f"Order {order['order_id']} could not be cancelled: {result.reason}")
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I was unable to cancel the order due to a system error.")
    return outcome


_PARTIAL_AMOUNT_RE = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)|\b(\d+(?:\.\d{1,2})?)\s?(?:dollars|usd)\b", re.I)


def _extract_requested_amount(text: str, order_total: float) -> float | None:
    """A customer-stated partial-refund amount (spec: Phase 8.3) -
    `RefundRequest.amount` already supports any value up to the order
    total (app.tools.refunds.create_refund_request), this just stops
    always passing the full total. Requires an explicit `$`/`dollars`/
    `usd` marker rather than any bare number, to avoid misreading an
    order id or quantity as a dollar amount. Returns None (caller falls
    back to a full refund) if nothing matches OR the parsed amount is not
    positive (spec: Phase 12 audit - "$0 refund"/a mis-extracted "$0.99
    shipping fee" aside is never a meaningful refund amount; treating it
    as "no amount stated" and falling back to a full refund is more useful
    than creating a real, pointless $0 RefundRequest for a human to
    review). The regex itself never captures a leading '-' (`\\d+` has no
    sign), so a negative amount can never reach here in the first place."""
    match = _PARTIAL_AMOUNT_RE.search(text)
    if not match:
        return None
    parsed = float(match.group(1) or match.group(2))
    if parsed <= 0:
        return None
    return min(parsed, order_total)


async def resolve_refund(
    ctx: ToolContext,
    customer_id: str,
    *,
    confirmed: bool,
    conversation_id: str,
    message_id: str,
    message: str = "",
    history: list[dict] | None = None,
    llm: LLMProvider | None = None,
    retriever: Retriever | None = None,
    **_,
) -> ResolutionOutcome:
    order, outcome = await _handle_order_lookup(ctx, customer_id)
    if not order:
        return outcome

    # spec: Phase 12 - REFUND/RETURNS both route here and previously created
    # the refund request regardless of how long ago the order was delivered
    # (no code anywhere checked this - confirmed by reading
    # app.tools.refunds.create_refund_request before adding this gate). Runs
    # before the confirmation prompt so a clearly-out-of-window request is
    # declined immediately rather than asking the customer to confirm
    # something that's about to be refused anyway. `llm`/`retriever` are
    # optional (defensive default None, never actually None from the only
    # real call site in gather_resolution_facts) so this degrades to
    # today's unconditional-refund behavior if either is unavailable,
    # exactly like a missing policy doc or missing delivery date does
    # inside check_commerce_policy itself. ORDER_CANCEL deliberately gets
    # no equivalent gate here - see resolve_order_cancel's docstring for why.
    if llm is not None and retriever is not None:
        reference_date: str | None = None
        try:
            shipping = await order_tools.get_shipping_status(
                ctx, order_tools.GetShippingStatusArgs(customer_id=customer_id, order_id=order["order_id"])
            )
            reference_date = shipping.estimated_delivery
        except ToolError:
            pass
        policy_result = await check_commerce_policy(
            retriever,
            llm,
            tenant_id=ctx.tenant_id,
            intent="REFUND",  # RETURNS shares the exact same refund-policy document/query
            order_status=order["status"],
            order_reference_date=reference_date,
        )
        if policy_result.decision == "deny":
            outcome.facts.append(
                f"I'm unable to process this request: {policy_result.reason} "
                f"(per our {policy_result.policy_title or 'refund policy'})."
            )
            return outcome

    requested_amount = _extract_requested_amount(message, order["total_amount"])
    if requested_amount is None and history:
        # A partial amount stated on the turn BEFORE the customer's "yes"
        # confirmation would otherwise be lost - this turn's message
        # (e.g. "yes") carries no amount at all. Scan the customer's own
        # prior turns, most recent first, for one instead of silently
        # reverting to a full refund on confirmation.
        for turn in reversed(history):
            if turn.get("role") != "user":
                continue
            requested_amount = _extract_requested_amount(turn.get("content", ""), order["total_amount"])
            if requested_amount is not None:
                break
    is_partial = requested_amount is not None and requested_amount < order["total_amount"]
    amount = requested_amount if requested_amount is not None else order["total_amount"]

    if not confirmed:
        outcome.pending_confirmation = True
        refund_description = f"a refund of {amount} {order['currency']}" if is_partial else "a full refund"
        outcome.facts.append(
            f"Found order {order['order_id']} for {order['total_amount']} {order['currency']}. "
            f"Please confirm you would like {refund_description} for this order."
        )
        return outcome
    try:
        idempotency_key = build_idempotency_key(conversation_id, "refund", message_id)
        result = await refund_tools.create_refund_request(
            ctx,
            refund_tools.CreateRefundRequestArgs(
                customer_id=customer_id,
                order_id=order["order_id"],
                amount=amount,
                reason="Customer-requested refund",
                idempotency_key=idempotency_key,
                customer_confirmed=True,
            ),
        )
        outcome.tool_calls.append({"tool": "create_refund_request", "args": {"order_id": order["order_id"]}})
        outcome.tool_results.append({"tool": "create_refund_request", "result": result.model_dump()})
        outcome.awaiting_approval = True  # refunds always require human approval per policy matrix
        outcome.facts.append(
            f"A refund request for {result.amount} has been created (status: {result.status}) "
            "and is pending human approval before it is processed."
        )
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I was unable to create the refund request due to a system error.")
    return outcome


async def resolve_payment_failure(ctx: ToolContext, customer_id: str, **_) -> ResolutionOutcome:
    order, outcome = await _handle_order_lookup(ctx, customer_id)
    if not order:
        return outcome
    try:
        result = await payment_tools.get_payment_status(
            ctx, payment_tools.GetPaymentStatusArgs(customer_id=customer_id, order_id=order["order_id"])
        )
        outcome.tool_calls.append({"tool": "get_payment_status", "args": {"order_id": order["order_id"]}})
        outcome.tool_results.append({"tool": "get_payment_status", "result": result.model_dump()})
        outcome.facts.append(
            f"Payment for order {order['order_id']} is '{result.status}'"
            + (f" ({result.failure_reason})" if result.failure_reason else "") + "."
        )
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I could not retrieve payment status due to a system error.")
    return outcome


async def resolve_subscription(
    ctx: ToolContext, customer_id: str, *, message: str, confirmed: bool, **_
) -> ResolutionOutcome:
    outcome = ResolutionOutcome()
    try:
        sub = await subscription_tools.get_subscription(
            ctx, subscription_tools.GetSubscriptionArgs(customer_id=customer_id)
        )
        outcome.tool_calls.append({"tool": "get_subscription", "args": {"customer_id": customer_id}})
        outcome.tool_results.append({"tool": "get_subscription", "result": sub.model_dump()})
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I could not find an active subscription on this account.")
        return outcome

    wants_cancel = bool(re.search(r"\bcancel\b", message, re.I))
    if not wants_cancel:
        outcome.facts.append(f"Your subscription plan is '{sub.plan}', status '{sub.status}'.")
        return outcome

    if not confirmed:
        outcome.pending_confirmation = True
        outcome.facts.append(f"Please confirm you would like to cancel your '{sub.plan}' subscription.")
        return outcome

    result = await subscription_tools.update_subscription(
        ctx,
        subscription_tools.UpdateSubscriptionArgs(
            customer_id=customer_id, new_status="cancelled", customer_confirmed=True
        ),
    )
    outcome.tool_calls.append({"tool": "update_subscription", "args": {"new_status": "cancelled"}})
    outcome.tool_results.append({"tool": "update_subscription", "result": result.model_dump()})
    outcome.facts.append("Your subscription has been cancelled.")
    return outcome


# Two deliberately narrower patterns rather than one loose one - a bare
# "to <word>" (e.g. "I want to change my plan") would otherwise capture
# "change" as a plan name. Require either an explicit "plan" suffix
# (any case) or a capitalized word right after "to" (plan names in this
# app - "Pro", "Enterprise" - are proper nouns; a lowercase word there is
# almost always a verb, not a plan name, so this branch is intentionally
# NOT case-insensitive).
_PLAN_TARGET_WITH_SUFFIX_RE = re.compile(r"\bto\s+(?:the\s+)?([a-zA-Z][a-zA-Z0-9_-]*)\s+plan\b", re.I)
_PLAN_TARGET_CAPITALIZED_RE = re.compile(r"\bto\s+(?:the\s+)?([A-Z][a-zA-Z0-9_-]*)\b")


def _extract_target_plan(text: str) -> str | None:
    match = _PLAN_TARGET_WITH_SUFFIX_RE.search(text) or _PLAN_TARGET_CAPITALIZED_RE.search(text)
    return match.group(1) if match else None


async def resolve_subscription_change(
    ctx: ToolContext,
    customer_id: str,
    *,
    message: str = "",
    confirmed: bool,
    history: list[dict] | None = None,
    **_,
) -> ResolutionOutcome:
    """spec: Phase 8.3 - upgrade/downgrade, distinct from resolve_subscription's
    cancel-only handling. Requires the target plan to be named explicitly
    in the message (rule 17: no inferred/guessed plan) - `_PLAN_TARGET_RE`
    looks for "to <word>" / "to the <word> plan"."""
    outcome = ResolutionOutcome()
    try:
        sub = await subscription_tools.get_subscription(
            ctx, subscription_tools.GetSubscriptionArgs(customer_id=customer_id)
        )
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I could not find an active subscription on this account.")
        return outcome

    target_plan = _extract_target_plan(message)
    if target_plan is None and history:
        # Same multi-turn gap as resolve_refund's amount - a bare "yes"
        # confirmation reply carries no plan name at all, so recover it
        # from the customer's own prior turn instead of escalating a
        # request that was already answerable.
        for turn in reversed(history):
            if turn.get("role") != "user":
                continue
            target_plan = _extract_target_plan(turn.get("content", ""))
            if target_plan is not None:
                break
    if target_plan is None:
        outcome.escalation_reason = "Could not determine which plan the customer wants to switch to"
        return outcome

    if target_plan.lower() == sub.plan.lower():
        outcome.facts.append(f"Your subscription is already on the '{sub.plan}' plan.")
        return outcome

    if not confirmed:
        outcome.pending_confirmation = True
        outcome.facts.append(
            f"Please confirm you would like to switch your subscription from '{sub.plan}' to '{target_plan}'."
        )
        return outcome

    result = await subscription_tools.update_subscription(
        ctx,
        subscription_tools.UpdateSubscriptionArgs(
            customer_id=customer_id, new_plan=target_plan, customer_confirmed=True
        ),
    )
    outcome.tool_calls.append({"tool": "update_subscription", "args": {"new_plan": target_plan}})
    outcome.tool_results.append({"tool": "update_subscription", "result": result.model_dump()})
    outcome.facts.append(f"Your subscription plan has been changed to '{result.plan}'.")
    return outcome


async def resolve_address_change(ctx: ToolContext, customer_id: str, **_) -> ResolutionOutcome:
    """spec: Phase 8.3 - deliberately always escalates rather than
    attempting to parse a full mailing address out of free text (rule 17:
    no deterministic logic can safely do that here - unlike a plan name
    or a dollar amount, an address has no single reliable marker to
    regex for). This is the internal-DB-resolver path only; a connected
    storefront's LLM-driven tool selection CAN extract structured address
    fields from the message (see resolve_via_storefront/propose_external_tool_call),
    so this always-escalate behavior only actually applies to a tenant
    with no storefront connected - also a defensible package-redirect-fraud
    safeguard on its own terms, not purely a technical limitation."""
    order, outcome = await _handle_order_lookup(ctx, customer_id)
    if not order:
        return outcome
    if order["status"] in order_tools.NON_ADDRESS_CHANGEABLE_STATUSES:
        outcome.facts.append(
            f"Order {order['order_id']} is already '{order['status']}' - its shipping address can no "
            "longer be changed."
        )
        return outcome
    outcome.escalation_reason = "Shipping address changes require verification by a team member"
    return outcome


async def resolve_payment_retry(
    ctx: ToolContext, customer_id: str, *, confirmed: bool, **_
) -> ResolutionOutcome:
    order, outcome = await _handle_order_lookup(ctx, customer_id)
    if not order:
        return outcome
    if not confirmed:
        outcome.pending_confirmation = True
        outcome.facts.append(
            f"Found order {order['order_id']}. Please confirm you would like to retry the payment "
            "for this order."
        )
        return outcome
    try:
        result = await payment_tools.retry_payment(
            ctx,
            payment_tools.RetryPaymentArgs(
                customer_id=customer_id, order_id=order["order_id"], customer_confirmed=True
            ),
        )
        outcome.tool_calls.append({"tool": "retry_payment", "args": {"order_id": order["order_id"]}})
        outcome.tool_results.append({"tool": "retry_payment", "result": result.model_dump()})
        if result.retried:
            outcome.facts.append(
                f"Payment for order {order['order_id']} was retried and is now '{result.status}'."
            )
        else:
            outcome.facts.append(f"Payment for order {order['order_id']} was not retried: {result.reason}")
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I was unable to retry the payment due to a system error.")
    return outcome


async def resolve_password_reset(ctx: ToolContext, customer_id: str, **_) -> ResolutionOutcome:
    outcome = ResolutionOutcome()
    try:
        result = await customer_tools.reset_password(
            ctx, customer_tools.ResetPasswordArgs(customer_id=customer_id)
        )
        outcome.tool_calls.append({"tool": "reset_password", "args": {"customer_id": customer_id}})
        outcome.tool_results.append({"tool": "reset_password", "result": result.model_dump()})
        outcome.facts.append("A password-reset verification email has been sent to your registered address.")
    except ToolError as exc:
        outcome.errors.append({"code": exc.code, "message": exc.message})
        outcome.facts.append("I could not start the password reset due to a system error.")
    return outcome


async def resolve_from_knowledge(
    retrieved_documents: list[RetrievedDocument],
    *,
    ctx: ToolContext | None = None,
    llm: LLMProvider | None = None,
    message: str = "",
    **_,
) -> ResolutionOutcome:
    outcome = ResolutionOutcome()
    if retrieved_documents:
        for doc in retrieved_documents:
            outcome.facts.append(f"[{doc.title}] {doc.text}")
        return outcome

    # Knowledge base had nothing - try the external-tool fallback (spec:
    # Phase 6 MCP, Phase 7 generalized to also cover OpenAPI-described
    # REST APIs) before giving up. ctx/llm are only absent in call sites
    # that predate this feature (there are none left in this codebase,
    # but the default keeps this function safe to call without them, e.g.
    # from a future test that doesn't need the external-tool path).
    if ctx is not None and llm is not None:
        proposal = await propose_external_tool_call(ctx, llm, message)
        if proposal is not None:
            outcome.tool_calls.append(
                {"tool": f"{proposal.source}:{proposal.tool_name}", "args": proposal.arguments}
            )
            outcome.awaiting_approval = True
            # Field name kept as `pending_mcp_call` (not renamed to
            # something source-neutral) so a workflow run already
            # interrupted awaiting approval before this generalization
            # deployed still resumes correctly - only its contents grew
            # a `source` key (+ method/path/param_locations for openapi).
            outcome.pending_mcp_call = {
                "integration_id": proposal.integration_id,
                "integration_name": proposal.integration_name,
                "source": proposal.source,
                "tool_name": proposal.tool_name,
                "arguments": proposal.arguments,
                "method": proposal.method,
                "path": proposal.path,
                "param_locations": proposal.param_locations,
                "input_schema": proposal.input_schema,
            }
            outcome.facts.append(
                f"Proposing to call the connected '{proposal.integration_name}' tool "
                f"'{proposal.tool_name}' with arguments {proposal.arguments} - pending human "
                "approval before it runs."
            )
            return outcome

    outcome.escalation_reason = "No reliable knowledge found for this question"
    return outcome


INTENT_RESOLVERS: dict[str, Callable[..., Awaitable[ResolutionOutcome]]] = {
    "ORDER_STATUS": resolve_order_status,
    "SHIPPING": resolve_order_status,
    "ORDER_CANCEL": resolve_order_cancel,
    "REFUND": resolve_refund,
    "RETURNS": resolve_refund,
    "PAYMENT_FAILURE": resolve_payment_failure,
    "SUBSCRIPTION": resolve_subscription,
    "PASSWORD_RESET": resolve_password_reset,
    "ACCOUNT_ACCESS": resolve_password_reset,
    # spec: Phase 8.3 - EXCHANGE deliberately has NO entry here (see
    # COMMERCE_INTENTS's comment below) - it only ever resolves via a
    # connected storefront.
    "SUBSCRIPTION_CHANGE": resolve_subscription_change,
    "ADDRESS_CHANGE": resolve_address_change,
    "PAYMENT_RETRY": resolve_payment_retry,
}

# Every intent INTENT_RESOLVERS answers using this app's OWN internal
# orders/payments/subscriptions tables - the set that means something
# different for a tenant whose real commerce data lives in a connected
# external storefront instead (spec: Phase 7 A2). PASSWORD_RESET/
# ACCOUNT_ACCESS are deliberately excluded - those are account operations
# on THIS platform, not the storefront's concern, regardless of whether
# one is connected. EXCHANGE is included here (so a connected storefront
# handles it) despite having no INTENT_RESOLVERS entry at all (spec:
# Phase 8.3) - this app's flat Order model has no SKU/variant/line-item
# concept to represent an exchange correctly, so there is deliberately no
# internal fallback; see KNOWLEDGE_INTENTS below for what a
# storefront-less tenant gets instead.
COMMERCE_INTENTS = {
    "ORDER_STATUS", "SHIPPING", "ORDER_CANCEL", "REFUND", "RETURNS", "PAYMENT_FAILURE", "SUBSCRIPTION",
    "SUBSCRIPTION_CHANGE", "ADDRESS_CHANGE", "PAYMENT_RETRY", "EXCHANGE",
}

KNOWLEDGE_INTENTS = {
    "BILLING", "PRODUCT_INFORMATION", "TECHNICAL_SUPPORT", "SUBSCRIPTION", "SHIPPING", "RETURNS",
    # EXCHANGE has no INTENT_RESOLVERS entry - a storefront-less tenant
    # falls through to here, getting a real "no reliable knowledge found"
    # escalation (resolve_from_knowledge) instead of a silent no-op.
    "EXCHANGE",
}


async def _get_storefront_integration(ctx: ToolContext) -> Integration | None:
    """The tenant's designated storefront (spec: Phase 7 A2) - an enabled
    `mcp` or `openapi` integration tagged `config.role == "storefront"`.
    First match wins if more than one is tagged (mirrors
    `IntegrationRepository.get_enabled_by_type`'s "exactly one active
    connector in the common case" assumption for JIRA/SMTP) - this
    codebase doesn't support routing different commerce intents to
    different storefronts."""
    repo = IntegrationRepository(ctx.session, ctx.tenant_id)
    for type_ in ("openapi", "mcp"):
        for integration in await repo.list_enabled_by_type(type_):
            if integration.config.get("role") == "storefront":
                return integration
    return None


def _extract_order_id_from_arguments(arguments: dict[str, Any]) -> str | None:
    """Best-effort only (spec: Phase 8.4) - there's no fixed argument name
    for "the order this call is about" across arbitrary connected
    storefronts, so this just looks for any string-valued argument whose
    key mentions "order" (covers `order_id`, `orderId`, `order_number`,
    etc.). Used to opportunistically correlate a later inbound webhook
    back to this conversation - never relied on for anything else, so a
    miss here is silently fine, not an error."""
    for key, value in arguments.items():
        if "order" in key.lower() and isinstance(value, str):
            return value
    return None


_ORDER_STATUS_KEY_HINTS = ("status",)
_ORDER_DATE_KEY_HINTS = ("delivered", "delivery", "deliveredat", "deliverydate", "shippedat")


def _find_first_string_value(obj: Any, key_hints: tuple[str, ...]) -> str | None:
    """Best-effort recursive scan of an arbitrary nested dict/list (an
    external storefront's own response shape, never controlled by this
    app - e.g. the real observed `{"result": {"data": {...}}}` nesting
    seen live-testing this session) for a string value whose key suggests
    one of `key_hints`. Mirrors `_extract_order_id_from_arguments`'s own
    "best-effort only, a miss is silently fine" precedent - used only to
    feed the policy-check gate below, never anything customer-facing."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and any(hint in key.lower().replace("_", "") for hint in key_hints):
                return value
        for value in obj.values():
            found = _find_first_string_value(value, key_hints)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_string_value(item, key_hints)
            if found is not None:
                return found
    return None


async def _lookup_order_snapshot_via_storefront(
    ctx: ToolContext, llm: LLMProvider, storefront: Integration, order_id: str
) -> tuple[str | None, str | None]:
    """Best-effort, read-only (status, reference_date) lookup used ONLY to
    feed app.agents.policy_check's eligibility gate for a storefront-routed
    REFUND/RETURNS request (spec: Phase 12) - never for ORDER_CANCEL (see
    resolve_order_cancel's docstring). A second, narrower
    `propose_external_tool_call` call targeting the same storefront - the
    catalog has no separate "find a read operation for this order"
    primitive, so this is the same LLM-driven selection mechanism already
    used for the real proposal, just given a status-lookup-shaped
    synthetic message. Returns (None, None) on anything short of a clean
    read (no matching operation found, a mutating one selected instead, or
    the call fails) - the caller treats that identically to "no data
    available", never as an error; check_commerce_policy already degrades
    to insufficient_data for either input being None."""
    try:
        proposal = await propose_external_tool_call(
            ctx,
            llm,
            f"What is the current status and delivery date of order {order_id}?",
            role="storefront",
        )
    except Exception:
        logger.warning("policy_check_order_lookup_proposal_failed", order_id=order_id, exc_info=True)
        return None, None
    if proposal is None or proposal.is_mutating:
        return None, None
    try:
        result = await execute_proposal(storefront, proposal)
    except IntegrationError:
        return None, None
    return (
        _find_first_string_value(result, _ORDER_STATUS_KEY_HINTS),
        _find_first_string_value(result, _ORDER_DATE_KEY_HINTS),
    )


async def resolve_via_storefront(
    ctx: ToolContext,
    llm: LLMProvider,
    message: str,
    storefront: Integration,
    conversation_id: str,
    *,
    intent: str = "",
    retriever: Retriever | None = None,
) -> ResolutionOutcome:
    """Routes a commerce-shaped intent to the tenant's connected
    storefront instead of this app's internal orders/payments/
    subscriptions tables (spec: Phase 7 A2) - this is what makes "the AI
    runs the full order lifecycle against our storefront" real, not just
    a last-resort fallback nobody's commerce question ever reaches
    (INTENT_RESOLVERS already "succeeds" with "no orders found" for those
    intents, so the plain fallback in resolve_from_knowledge is never
    even consulted for them).

    Deliberately skips the customer-confirmation round-trip
    (`customer_already_confirmed`) that the internal mutating resolvers
    use: re-deriving the SAME proposed tool call on a bare "yes" reply
    would need the LLM to recover full context from conversation history
    rather than the internal resolvers' cheap idempotent DB re-lookup, a
    materially more complex (and more failure-prone) mechanism. The
    mandatory staff-approval gate below is the actual hard safety
    boundary for an unreviewed external integration - the customer
    self-confirmation step is a UX nicety on top of it for the internal
    tools, not the safety boundary itself.
    """
    outcome = ResolutionOutcome()
    proposal = await propose_external_tool_call(ctx, llm, message, role="storefront")
    if proposal is None:
        outcome.escalation_reason = "No matching storefront operation found for this request"
        return outcome

    # spec: Phase 12 - a storefront-routed REFUND/RETURNS previously
    # proposed the mutating call with no policy check at all (confirmed:
    # the demo storefront's own /orders/{id}/refund only validates
    # amount <= total, no day-window check exists anywhere for this path
    # either). ORDER_CANCEL is excluded - the storefront's own status
    # check on the mutating call already enforces that rule deterministically
    # (demo_storefront's NON_MUTABLE_STATUSES), matching resolve_order_cancel's
    # reasoning for the internal path. Order status/date come from a second,
    # best-effort read lookup - see _lookup_order_snapshot_via_storefront's
    # docstring for why this app can't just read them off `proposal.arguments`
    # (a storefront's mutating operations typically take only an order id).
    if intent in {"REFUND", "RETURNS"} and proposal.is_mutating and retriever is not None:
        order_id_for_policy = _extract_order_id_from_arguments(proposal.arguments)
        order_status: str | None = None
        order_date: str | None = None
        if order_id_for_policy is not None:
            order_status, order_date = await _lookup_order_snapshot_via_storefront(
                ctx, llm, storefront, order_id_for_policy
            )
        policy_result = await check_commerce_policy(
            retriever,
            llm,
            tenant_id=ctx.tenant_id,
            intent=intent,
            order_status=order_status,
            order_reference_date=order_date,
        )
        if policy_result.decision == "deny":
            outcome.facts.append(
                f"I'm unable to proceed with this request: {policy_result.reason} "
                f"(per our {policy_result.policy_title or 'policy'})."
            )
            return outcome

    # spec: Phase 8.4 - best-effort correlation for a later inbound
    # webhook (see app.api.routes.webhooks) to find its way back to this
    # conversation. Recorded as soon as a proposal matches - whether it
    # then auto-executes or waits for approval - since either way this
    # conversation is now about this order.
    order_id = _extract_order_id_from_arguments(proposal.arguments)
    if order_id is not None:
        conversation = await ConversationRepository(ctx.session, ctx.tenant_id).get(conversation_id)
        if conversation is not None:
            conversation.metadata_json = {**conversation.metadata_json, "last_order_id": order_id}
            await ctx.session.flush()

    if not proposal.is_mutating and storefront.config.get("auto_execute_reads", False):
        # Explicit per-integration opt-in only, and only for a read
        # operation - see app.agents.external_tools's module docstring
        # for why this is the one case that skips the approval ticket.
        start = time.perf_counter()
        try:
            result = await execute_proposal(storefront, proposal)
        except IntegrationError as exc:
            await record_external_tool_execution(
                ctx.session,
                tenant_id=ctx.tenant_id,
                workflow_run_id=ctx.workflow_run_id,
                customer_id=ctx.requesting_customer_id,
                tool_name=f"{proposal.source}:{proposal.tool_name}",
                arguments=proposal.arguments,
                result={"error": str(exc)},
                success=False,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
            logger.warning(
                "storefront_auto_execute_failed",
                integration_id=storefront.id,
                tool=proposal.tool_name,
                error=str(exc),
            )
            outcome.escalation_reason = f"Storefront lookup failed: {exc}"
            return outcome
        duration_ms = (time.perf_counter() - start) * 1000
        await record_external_tool_execution(
            ctx.session,
            tenant_id=ctx.tenant_id,
            workflow_run_id=ctx.workflow_run_id,
            customer_id=ctx.requesting_customer_id,
            tool_name=f"{proposal.source}:{proposal.tool_name}",
            arguments=proposal.arguments,
            result=result,
            success=True,
            duration_ms=duration_ms,
        )
        result_text = str(result.get("text") or result.get("result") or "completed with no output")
        logger.info(
            "storefront_auto_execute_succeeded",
            integration_id=storefront.id,
            integration_name=proposal.integration_name,
            tool=proposal.tool_name,
            duration_ms=round(duration_ms, 1),
        )
        outcome.tool_calls.append(
            {"tool": f"{proposal.source}:{proposal.tool_name}", "args": proposal.arguments}
        )
        outcome.facts.append(f"Checked our connected {proposal.integration_name}: {result_text}")
        return outcome

    outcome.tool_calls.append({"tool": f"{proposal.source}:{proposal.tool_name}", "args": proposal.arguments})
    outcome.awaiting_approval = True
    outcome.pending_mcp_call = {
        "integration_id": proposal.integration_id,
        "integration_name": proposal.integration_name,
        "source": proposal.source,
        "tool_name": proposal.tool_name,
        "arguments": proposal.arguments,
        "method": proposal.method,
        "path": proposal.path,
        "param_locations": proposal.param_locations,
        "input_schema": proposal.input_schema,
    }
    outcome.facts.append(
        f"Proposing to call the connected '{proposal.integration_name}' tool "
        f"'{proposal.tool_name}' with arguments {proposal.arguments} - pending human "
        "approval before it runs."
    )
    return outcome


async def gather_resolution_facts(
    ctx: ToolContext,
    *,
    intent: str,
    customer_id: str,
    conversation_id: str,
    message_id: str,
    message: str,
    history: list[dict],
    retrieved_documents: list[RetrievedDocument],
    llm: LLMProvider | None = None,
    retriever: Retriever | None = None,
) -> ResolutionOutcome:
    if intent in COMMERCE_INTENTS and llm is not None:
        storefront = await _get_storefront_integration(ctx)
        if storefront is not None:
            return await resolve_via_storefront(
                ctx, llm, message, storefront, conversation_id, intent=intent, retriever=retriever
            )

    confirmed = customer_already_confirmed(history, message)
    resolver = INTENT_RESOLVERS.get(intent)
    if resolver is not None:
        return await resolver(
            ctx,
            customer_id,
            confirmed=confirmed,
            message=message,
            conversation_id=conversation_id,
            message_id=message_id,
            history=history,
            llm=llm,
            retriever=retriever,
        )
    if intent in KNOWLEDGE_INTENTS or intent == "UNKNOWN":
        return await resolve_from_knowledge(retrieved_documents, ctx=ctx, llm=llm, message=message)
    return ResolutionOutcome()


RESPONSE_TEMPLATE_RULES = (
    "Write a concise, professional, empathetic reply to the customer using ONLY "
    "the facts listed below. Structure it around: what I know, what I checked, "
    "what I changed (only if a tool result confirms a change happened), what I "
    "cannot verify, and what happens next. Never state that an action succeeded "
    "unless it is explicitly listed as having happened in the facts."
)


async def draft_response(llm: LLMProvider, *, message: str, facts: list[str]) -> str:
    # Collapse any internal newlines (e.g. a multi-paragraph knowledge chunk)
    # so every fact renders as exactly one bulleted line - both for prompt
    # readability and because MockLLMProvider's fact extraction is line-based.
    single_line_facts = [" ".join(f.split()) for f in facts]
    facts_text = (
        "\n".join(f"- {f}" for f in single_line_facts)
        if single_line_facts
        else "- No verified facts are available."
    )
    messages = build_prompt_messages(
        business_policies="",
        developer_rules=f"{RESPONSE_TEMPLATE_RULES}\n\nVERIFIED FACTS:\n{facts_text}",
        retrieved_knowledge=[],
        customer_message=message,
    )
    return await llm.generate(messages)
