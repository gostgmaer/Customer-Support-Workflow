"""WooCommerce REST API v3 client. Auth is `basic` (consumer_key as
username, consumer_secret as password - WooCommerce's own convention).

Staff-triggered only (`POST /support/tickets/{id}/woocommerce-lookup`) -
not wired into the LLM's autonomous tool-calling loop, since that would
mean an untested, real external call happening inside a path this
project can't verify without a live store (see docs/SECURITY.md).
"""

from __future__ import annotations

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import build_http_client, short_response_body


class WooCommerceClient:
    def __init__(self, integration: Integration) -> None:
        self._integration = integration

    async def find_order(self, order_number: str) -> dict | None:
        async with build_http_client(self._integration) as client:
            response = await client.get("/wp-json/wc/v3/orders", params={"search": order_number})
        if response.status_code >= 400:
            raise IntegrationError(
                f"WooCommerce lookup failed ({response.status_code}): {short_response_body(response.text)}"
            )
        results = response.json()
        return results[0] if results else None
