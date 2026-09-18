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
}
READ_ONLY_DATA_INTENTS = {
    "ORDER_STATUS", "SHIPPING", "PAYMENT_FAILURE", "BILLING", "ACCOUNT_ACCESS",
    "PASSWORD_RESET", "SUBSCRIPTION",
}
KNOWLEDGE_INTENTS = {
    "PRODUCT_INFORMATION", "TECHNICAL_SUPPORT", "BUG_REPORT", "FEATURE_REQUEST",
    "PRIVACY", "COMPLAINT", "UNKNOWN", "EXCHANGE",
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
