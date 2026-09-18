"""app.integrations.stripe.StripeClient - HTTP calls mocked with respx
against fixture responses shaped to match Stripe's real, public API
documentation (spec: Phase 9.4b). No real Stripe account or test-mode
keys exist yet - see docs/ARCHITECTURE.md's "Payment gateway (Stripe)"
for the documented live-verification gap.
"""

from __future__ import annotations

import respx
from httpx import Response

from app.db.base import DEFAULT_TENANT_ID
from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.stripe import StripeClient


def _stripe_integration() -> Integration:
    return Integration(
        id="int_stripe_1",
        tenant_id=DEFAULT_TENANT_ID,
        name="Test Stripe",
        type="stripe",
        base_url="https://api.stripe.com",
        auth_type="bearer",
        encrypted_credentials=encode_credentials({"token": "sk_test_abc123"}),
        config={"webhook_secret": "whsec_test"},
        enabled=True,
        created_by="staff_1",
    )


@respx.mock
async def test_create_refund_sends_form_encoded_body_in_cents():
    route = respx.post("https://api.stripe.com/v1/refunds").mock(
        return_value=Response(200, json={"id": "re_123", "status": "pending"})
    )
    client = StripeClient(_stripe_integration())

    result = await client.create_refund(payment_intent_id="pi_123", amount=19.99, reason="damaged item")

    assert result == {"id": "re_123", "status": "pending"}
    request = route.calls.last.request
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    body = request.content.decode()
    assert "payment_intent=pi_123" in body
    # 19.99 dollars -> 1999 cents, not a float-formatted dollar amount.
    assert "amount=1999" in body


@respx.mock
async def test_create_refund_raises_on_error_response():
    respx.post("https://api.stripe.com/v1/refunds").mock(
        return_value=Response(402, json={"error": {"message": "insufficient funds"}})
    )
    client = StripeClient(_stripe_integration())

    try:
        await client.create_refund(payment_intent_id="pi_123", amount=10.0)
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_retrieve_payment_intent_returns_the_real_status():
    respx.get("https://api.stripe.com/v1/payment_intents/pi_123").mock(
        return_value=Response(200, json={"id": "pi_123", "status": "requires_capture"})
    )
    client = StripeClient(_stripe_integration())

    result = await client.retrieve_payment_intent("pi_123")

    assert result["status"] == "requires_capture"


@respx.mock
async def test_confirm_payment_intent_posts_to_the_right_endpoint():
    route = respx.post("https://api.stripe.com/v1/payment_intents/pi_456/confirm").mock(
        return_value=Response(200, json={"id": "pi_456", "status": "succeeded"})
    )
    client = StripeClient(_stripe_integration())

    result = await client.confirm_payment_intent("pi_456")

    assert result["status"] == "succeeded"
    assert route.called


@respx.mock
async def test_confirm_payment_intent_raises_on_error():
    respx.post("https://api.stripe.com/v1/payment_intents/pi_456/confirm").mock(
        return_value=Response(400, json={"error": {"message": "already confirmed"}})
    )
    client = StripeClient(_stripe_integration())

    try:
        await client.confirm_payment_intent("pi_456")
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass


@respx.mock
async def test_get_balance_uses_bearer_auth_from_the_secret_key():
    route = respx.get("https://api.stripe.com/v1/balance").mock(
        return_value=Response(200, json={"available": [{"amount": 10000, "currency": "usd"}]})
    )
    client = StripeClient(_stripe_integration())

    result = await client.get_balance()

    assert result["available"][0]["amount"] == 10000
    assert route.calls.last.request.headers["Authorization"] == "Bearer sk_test_abc123"


@respx.mock
async def test_get_balance_raises_on_invalid_key():
    respx.get("https://api.stripe.com/v1/balance").mock(
        return_value=Response(401, json={"error": {"message": "Invalid API Key provided"}})
    )
    client = StripeClient(_stripe_integration())

    try:
        await client.get_balance()
        raise AssertionError("expected IntegrationError")
    except IntegrationError:
        pass
