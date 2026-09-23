"""In-memory demo data (spec: Phase 8.1).

Deliberately not a real database - this fixture exists to give the main
app's storefront-primary routing (app.agents.resolution.resolve_via_storefront)
a stable, committed target to call, replacing the throwaway/uncommitted
FastAPI script used to live-verify Phase A2. Restarting this service resets
all state, which is a feature for repeatable demos/tests, not a bug.
"""

from __future__ import annotations

from typing import Any

# One order already "delivered" so cancel/exchange/address-change correctly
# reject it - every new scenario needs both a happy path and a real
# rejection path to be worth live-verifying against.
#
# `customer_email` (spec: Phase 14) - added so this fixture actually has
# something for app.agents.external_tools.verify_resource_ownership to
# check. Before this field existed, this app's own committed demo
# storefront could not verify ownership for ANY order (a real, live gap
# discovered while building that check, not a hypothetical one) - a
# realistic external storefront's own order-lookup response would
# ordinarily carry a customer-identifying field, so adding one here makes
# this fixture a truer stand-in, not a workaround. Owners match the real
# seeded app customers in scripts/seed/seed_data.py (alice@example.com,
# bob@example.com) so a live cross-customer test is actually constructible.
ORDERS: dict[str, dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "status": "shipped",
        "carrier": "FastShip",
        "tracking_number": "TRK555",
        "total": 129.99,
        "customer_email": "alice@example.com",
        "shipping_address": {
            "line1": "12 Baker Street",
            "city": "Springfield",
            "postal_code": "62704",
            "country": "US",
        },
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "status": "processing",
        "carrier": None,
        "tracking_number": None,
        "total": 54.50,
        "customer_email": "bob@example.com",
        "shipping_address": {
            "line1": "88 Elm Street",
            "city": "Shelbyville",
            "postal_code": "62565",
            "country": "US",
        },
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "status": "delivered",
        "carrier": "SlowPost",
        "tracking_number": "TRK009",
        "total": 89.00,
        "customer_email": "alice@example.com",
        "shipping_address": {
            "line1": "4 Main Street",
            "city": "Ogdenville",
            "postal_code": "62701",
            "country": "US",
        },
    },
}

# Keyed by a customer-facing reference, not an internal id, to mirror how a
# real storefront's subscriptions API is usually addressed. `customer_email`
# added alongside ORDERS' (spec: Phase 14) for the same reason.
SUBSCRIPTIONS: dict[str, dict[str, Any]] = {
    "CUST-alice": {
        "customer_ref": "CUST-alice",
        "plan": "starter",
        "status": "active",
        "customer_email": "alice@example.com",
    },
}

# One payment that always retries successfully, one that always fails again -
# deterministic outcomes for testing both branches. `customer_email` mirrors
# each payment's own order (spec: Phase 14).
PAYMENTS: dict[str, dict[str, Any]] = {
    "PAY-2001": {
        "payment_id": "PAY-2001",
        "status": "failed",
        "order_id": "ORD-1002",
        "retryable": True,
        "customer_email": "bob@example.com",
    },
    "PAY-2002": {
        "payment_id": "PAY-2002",
        "status": "failed",
        "order_id": "ORD-1003",
        "retryable": False,
        "customer_email": "alice@example.com",
    },
}

NON_MUTABLE_STATUSES = {"delivered", "cancelled"}
