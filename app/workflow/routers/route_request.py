"""route_request conditional edge (spec §30).

A pure routing function (no side effects) - the actual tool/knowledge work
happens uniformly in the resolve_issue node via
app.agents.resolution.gather_resolution_facts, which dispatches on intent
the same way. These branch labels exist so the graph shape matches the
spec's diagram and so `state["route"]` is observable/testable, not because
the four branches do materially different work.
"""

from __future__ import annotations

from typing import Literal

from app.config import get_settings
from app.domain.enums.intent import ALWAYS_ESCALATE_INTENTS
from app.workflow.state import SupportState

Route = Literal["knowledge_search", "customer_data", "action_required", "human_escalation"]

MUTATING_INTENTS = {
    "ORDER_CANCEL", "REFUND", "RETURNS", "SUBSCRIPTION_CHANGE", "ADDRESS_CHANGE", "PAYMENT_RETRY",
    # spec: Phase 13 - PROFILE_UPDATE is a new mutating intent (identity
    # change, always human-approved); ACCOUNT_ACCESS moved here from
    # READ_ONLY_DATA_INTENTS below since its resolver can now propose a
    # real mutation (account unlock). Neither resolver depends on
    # state["retrieved_documents"] (see this module's docstring - only
    # the "knowledge_search" route populates it), so routing them away
    # from knowledge_search is safe. BILLING deliberately NOT moved here
    # despite also gaining a mutation path (a duplicate-charge refund) -
    # see KNOWLEDGE_INTENTS's comment below for why.
    "PROFILE_UPDATE", "ACCOUNT_ACCESS",
}
READ_ONLY_DATA_INTENTS = {
    "ORDER_STATUS", "SHIPPING", "PAYMENT_FAILURE",
    "PASSWORD_RESET", "SUBSCRIPTION",
}
KNOWLEDGE_INTENTS = {
    "PRODUCT_INFORMATION", "TECHNICAL_SUPPORT", "BUG_REPORT", "FEATURE_REQUEST",
    "COMPLAINT", "UNKNOWN", "EXCHANGE",
    # spec: Phase 13 audit - a REAL pre-existing routing gap, found while
    # verifying RAG coverage, not introduced by this phase: BILLING was
    # previously in READ_ONLY_DATA_INTENTS ("customer_data" route), which
    # - like "action_required" - never runs knowledge_search_node
    # (app.workflow.nodes.route_nodes), so state["retrieved_documents"]
    # was ALWAYS empty for a BILLING message despite a real seeded
    # "Billing FAQ" doc existing. app.agents.resolution.resolve_billing's
    # RAG-fallback branch (invoices, general billing questions, promo
    # codes) needs real retrieval to ever ground an answer - moved here so
    # BILLING gets the "knowledge_search" route. resolve_billing's
    # duplicate-charge mutation path is unaffected either way, since
    # gather_resolution_facts dispatches on intent uniformly regardless
    # of route (this module's own docstring) - the route label never
    # gated which resolver runs, only whether retrieval ran first.
    "BILLING",
    # spec: Phase 13 - PRIVACY removed: it's now in ALWAYS_ESCALATE_INTENTS
    # (app.domain.enums.intent), checked before this set below, so its
    # membership here was already unreachable - removed for clarity, not
    # a behavior change.
}
ESCALATE_INTENTS = {i.value for i in ALWAYS_ESCALATE_INTENTS}


def route_request(state: SupportState) -> Route:
    intent = (state.get("intent") or "UNKNOWN")
    confidence = state.get("intent_confidence") or 0.0
    settings = get_settings()
    # spec §43: a tenant's DB-overridden threshold (app.config.dynamic_settings),
    # resolved once at run start - falls back to the env default when absent
    # (e.g. state built directly in a test).
    threshold = state.get("runtime_config", {}).get("confidence_intent", settings.confidence_intent)

    if intent in ESCALATE_INTENTS or state.get("requires_human"):
        return "human_escalation"
    if intent != "UNKNOWN" and confidence < threshold:
        return "human_escalation"
    if intent in MUTATING_INTENTS:
        return "action_required"
    if intent in READ_ONLY_DATA_INTENTS:
        return "customer_data"
    return "knowledge_search"
