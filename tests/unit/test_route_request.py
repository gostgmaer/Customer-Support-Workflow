"""app.workflow.routers.route_request - spec: Phase 8.3 added four new
intents (SUBSCRIPTION_CHANGE, ADDRESS_CHANGE, PAYMENT_RETRY, EXCHANGE),
each needing its own entry in this router's separately-maintained
MUTATING_INTENTS/READ_ONLY_DATA_INTENTS/KNOWLEDGE_INTENTS sets (distinct
from app.agents.resolution's same-named sets - the two have drifted from
each other before, see that module's COMMERCE_INTENTS comment).
"""

from __future__ import annotations

from app.workflow.routers.route_request import route_request


def _state(intent: str) -> dict:
    return {"intent": intent, "intent_confidence": 1.0, "runtime_config": {}}


def test_subscription_change_routes_to_action_required():
    assert route_request(_state("SUBSCRIPTION_CHANGE")) == "action_required"


def test_address_change_routes_to_action_required():
    assert route_request(_state("ADDRESS_CHANGE")) == "action_required"


def test_payment_retry_routes_to_action_required():
    assert route_request(_state("PAYMENT_RETRY")) == "action_required"


def test_exchange_routes_to_knowledge_search():
    # No internal resolver exists for EXCHANGE (storefront-only) - the
    # route label reflects that it's not a mutating internal-tool path.
    assert route_request(_state("EXCHANGE")) == "knowledge_search"


# --- Phase 13 ---


def test_profile_update_routes_to_action_required():
    assert route_request(_state("PROFILE_UPDATE")) == "action_required"


def test_account_access_routes_to_action_required():
    # Moved from customer_data (Phase 13) - its resolver can now propose a
    # real mutation (account unlock).
    assert route_request(_state("ACCOUNT_ACCESS")) == "action_required"


def test_billing_routes_to_knowledge_search():
    # A real, pre-existing routing gap found in Phase 13's audit: BILLING
    # used to route to customer_data, which (like action_required) never
    # runs knowledge_search_node - state["retrieved_documents"] was always
    # empty for a BILLING message despite a real seeded Billing FAQ doc.
    # resolve_billing's RAG-fallback branch needs real retrieval to ever
    # ground an answer, so BILLING now gets the knowledge_search route.
    assert route_request(_state("BILLING")) == "knowledge_search"


def test_privacy_routes_to_human_escalation():
    # Phase 13: PRIVACY moved into ALWAYS_ESCALATE_INTENTS - previously a
    # PRIVACY message produced an empty ResolutionOutcome() with no facts
    # and no escalation (it was in neither app.agents.resolution's
    # KNOWLEDGE_INTENTS nor INTENT_RESOLVERS).
    assert route_request(_state("PRIVACY")) == "human_escalation"
