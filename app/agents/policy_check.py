"""Policy-grounded eligibility gate for commerce actions (spec: Phase 12).

RETURNS/REFUND/ORDER_CANCEL previously routed straight to a resolver
(internal or storefront) and proposed/created the action without ever
consulting the actual policy documents in the knowledge base - a customer
well past a stated return window got the same "propose the refund"
treatment as one on day one. `route_request` sends these intents down the
`action_required` branch, which never runs `knowledge_search_node`, so
`retrieved_documents` is always empty for them - the knowledge base was
never in the loop for an action request, only for a pure informational
question like "what's your return policy?".

This module closes that gap with one narrow, bounded structured-output
LLM call: given the retrieved policy text plus whatever order data is
actually available, decide allow/deny/insufficient_data - never
open-ended reasoning, matching this codebase's existing `generate_structured`
pattern (see app.agents.classifier) rather than a free-form judgment call.
`insufficient_data` (no policy doc found, no order status/date to check
against, or the policy text doesn't clearly say either way) always means
"proceed exactly as before this feature existed" - this gate can only ever
make a request STRICTER by adding a clear denial, never stricter by
blocking on ambiguity, per the "escalate/proceed rather than guess" posture
used throughout this codebase's other structured-output call sites.

MockLLMProvider always returns insufficient_data for this schema (see
app.llm.providers.mock._build_commerce_eligibility, mirroring
_build_external_tool_selection's "mock defers real reasoning" precedent) -
so every existing MOCK_LLM=true test and live flow is unaffected unless a
test explicitly stubs this schema to exercise allow/deny.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.llm.base import LLMProvider
from app.observability.logging import get_logger
from app.rag.retriever import Retriever
from app.security.prompt_security import build_prompt_messages

logger = get_logger(__name__)

# Only intents with a real, seeded policy document behind them get a query
# here - REFUND and RETURNS share the same "refunds" category doc (see
# app.agents.resolution.INTENT_RESOLVERS, both already map to
# resolve_refund). An intent absent from this map always short-circuits to
# insufficient_data (proceed as before), not a KeyError.
_POLICY_QUERIES: dict[str, str] = {
    "ORDER_CANCEL": "order cancellation policy - which order statuses can be cancelled",
    "REFUND": "refund policy - return window in days from delivery",
    "RETURNS": "return policy - return window in days from delivery",
}


class CommerceEligibilityCheck(BaseModel):
    qualifies: Literal["yes", "no", "insufficient_data"] = Field(
        description=(
            "Whether the order qualifies for the customer's requested action under the "
            "given policy text. Answer 'no' ONLY if the policy text clearly and explicitly "
            "disallows this specific case. Answer 'insufficient_data' if the policy is "
            "silent/ambiguous, or a fact you'd need (an exact date, the order status) is "
            "missing or marked 'unknown' below. Never invent a rule not present in the text."
        )
    )
    reason: str = Field(description="One sentence explaining the decision, citing the policy text.")


@dataclass
class PolicyCheckResult:
    decision: Literal["allow", "deny", "insufficient_data"]
    reason: str | None = None
    policy_title: str | None = None


async def check_commerce_policy(
    retriever: Retriever,
    llm: LLMProvider,
    *,
    tenant_id: str,
    intent: str,
    order_status: str | None,
    order_reference_date: str | None,
) -> PolicyCheckResult:
    """`order_reference_date` is a best-effort ISO date string for "when did
    (or will) this order arrive" - the only fact a day-window policy like
    the refund policy actually needs. Neither this app's internal `Order`
    model nor the demo storefront fixture track a real delivery timestamp
    today (confirmed by reading both before writing this) - callers pass
    `None` when they have nothing better, and this function degrades to
    insufficient_data rather than guessing, exactly like a missing policy
    doc does."""
    query = _POLICY_QUERIES.get(intent)
    if query is None:
        return PolicyCheckResult(decision="insufficient_data")

    try:
        docs = await retriever.retrieve(query, tenant_id=tenant_id, top_k=1)
    except Exception:
        logger.warning("policy_check_retrieval_failed", intent=intent, exc_info=True)
        return PolicyCheckResult(decision="insufficient_data")

    if not docs:
        return PolicyCheckResult(decision="insufficient_data")

    policy_doc = docs[0]
    if order_status is None and order_reference_date is None:
        return PolicyCheckResult(decision="insufficient_data", policy_title=policy_doc.title)

    today = datetime.now(UTC).date().isoformat()
    rules = (
        "You are checking whether a customer's commerce request (cancel/return/refund) "
        "complies with the company's own policy text below. Base your answer only on that "
        "text and the order facts given - never on outside knowledge of typical retail "
        "policies.\n\n"
        f"POLICY TEXT:\n{policy_doc.text}\n\n"
        f"ORDER STATUS: {order_status or 'unknown'}\n"
        f"ORDER REFERENCE DATE (delivery date if known, else order placement date): "
        f"{order_reference_date or 'unknown'}\n"
        f"TODAY'S DATE: {today}"
    )
    messages = build_prompt_messages(
        business_policies="", developer_rules=rules, retrieved_knowledge=[], customer_message="",
    )
    try:
        result = await llm.generate_structured(messages, schema=CommerceEligibilityCheck)
    except Exception:
        logger.warning("policy_check_llm_failed", intent=intent, exc_info=True)
        return PolicyCheckResult(decision="insufficient_data", policy_title=policy_doc.title)

    _DECISION_MAP: dict[str, Literal["allow", "deny", "insufficient_data"]] = {
        "yes": "allow", "no": "deny", "insufficient_data": "insufficient_data",
    }
    decision = _DECISION_MAP[result.qualifies]
    if decision == "deny":
        logger.info(
            "commerce_policy_check_denied",
            intent=intent,
            policy_title=policy_doc.title,
            reason=result.reason,
        )
    return PolicyCheckResult(decision=decision, reason=result.reason, policy_title=policy_doc.title)
