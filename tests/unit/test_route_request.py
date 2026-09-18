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
