"""Stripe REST API client (spec: Phase 9.4b).

Shaped like `app.integrations.jira.JiraClient` - a small class taking an
`Integration`, each async method building an authenticated call via
`build_http_client` and raising `IntegrationError` on a non-2xx response.
One genuine deviation from every other client in this codebase (JIRA,
WooCommerce, MCP, OpenAPI, Confluence, Notion all send `json=...`):
Stripe's REST API is form-encoded (`application/x-www-form-urlencoded`),
not JSON - every method here sends `data=...`, not `json=...`.

Auth: Stripe's secret key is itself a bearer token
(`Authorization: Bearer sk_test_...`/`sk_live_...`), fitting this
codebase's existing `auth_type: "bearer"` (credentials key `token`) with
no new auth code needed.

Amounts are in the smallest currency unit (cents for USD), matching
Stripe's own API convention - callers of this module pass/receive
dollars-as-float (this app's existing convention everywhere else, e.g.
`Payment.amount`/`RefundRequest.amount`), converted at the boundary here
so the rest of the codebase never has to think in cents.

Built and tested entirely against respx-mocked HTTP shaped to match
Stripe's real, public API documentation - no real Stripe account or
test-mode keys exist yet to verify against live. See
docs/ARCHITECTURE.md's "Payment gateway (Stripe)" for the documented
live-verification gap and exactly what to do once real test keys exist.
"""

from __future__ import annotations

from typing import Any

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import build_http_client, short_response_body


def _to_cents(amount: float) -> int:
    return round(amount * 100)


class StripeClient:
    def __init__(self, integration: Integration) -> None:
        self._integration = integration

    async def create_refund(
        self, *, payment_intent_id: str, amount: float, reason: str = ""
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "payment_intent": payment_intent_id,
            "amount": _to_cents(amount),
        }
        if reason:
            data["metadata[reason]"] = reason[:500]
        async with build_http_client(self._integration) as client:
            response = await client.post("/v1/refunds", data=data)
        if response.status_code >= 400:
            raise IntegrationError(
                f"Stripe refund failed ({response.status_code}): {short_response_body(response.text)}"
            )
        return response.json()

    async def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        async with build_http_client(self._integration) as client:
            response = await client.get(f"/v1/payment_intents/{payment_intent_id}")
        if response.status_code >= 400:
            raise IntegrationError(
                f"Stripe payment intent lookup failed ({response.status_code}): "
                f"{short_response_body(response.text)}"
            )
        return response.json()

    async def confirm_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        async with build_http_client(self._integration) as client:
            response = await client.post(f"/v1/payment_intents/{payment_intent_id}/confirm")
        if response.status_code >= 400:
            raise IntegrationError(
                f"Stripe payment intent confirmation failed ({response.status_code}): "
                f"{short_response_body(response.text)}"
            )
        return response.json()

    async def get_balance(self) -> dict[str, Any]:
        """Cheapest real call that proves the API key works - used by
        app.integrations.health.test_connection, mirroring JIRA's
        `/rest/api/2/myself` and WooCommerce's order-list "is this key
        valid" checks."""
        async with build_http_client(self._integration) as client:
            response = await client.get("/v1/balance")
        if response.status_code >= 400:
            raise IntegrationError(
                f"Stripe balance check failed ({response.status_code}): {short_response_body(response.text)}"
            )
        return response.json()
