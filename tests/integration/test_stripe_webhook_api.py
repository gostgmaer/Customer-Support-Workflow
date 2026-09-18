"""POST /api/v1/webhooks/stripe/{integration_id} (spec: Phase 9.4) -
mirrors tests/integration/test_webhooks_api.py's shape for the
storefront webhook, using Stripe's own signing scheme instead.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.db.session import get_sessionmaker
from app.domain.models import Payment, RefundRequest


def _sign(payload: bytes, secret: str) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode() + payload
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


async def _create_stripe_integration(client, admin_staff_token, *, webhook_secret: str = "whsec_test") -> str:
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Test Stripe",
        "type": "stripe",
        "base_url": "https://api.stripe.com",
        "auth_type": "bearer",
        "credentials": {"token": "sk_test_abc"},
        "config": {"webhook_secret": webhook_secret},
    }
    response = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_payment_intent_succeeded_updates_the_matching_payment(
    client, admin_staff_token, seeded_customer, db_session
):
    integration_id = await _create_stripe_integration(client, admin_staff_token)

    async with get_sessionmaker()() as session:
        payment = Payment(
            order_id=seeded_customer["order_id"],
            customer_id=seeded_customer["customer_id"],
            status="failed",
            amount=42.0,
            gateway="stripe",
            gateway_payment_intent_id="pi_webhook_test_1",
        )
        session.add(payment)
        await session.commit()
        payment_id = payment.id

    payload = {
        "id": "evt_1",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_webhook_test_1", "status": "succeeded"}},
    }
    body = json.dumps(payload).encode()

    response = await client.post(
        f"/api/v1/webhooks/stripe/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body, "whsec_test")},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "handled": True}

    async with get_sessionmaker()() as session:
        reloaded = await session.get(Payment, payment_id)
        assert reloaded is not None
        assert reloaded.status == "succeeded"


@pytest.mark.asyncio
async def test_payment_intent_failed_updates_the_matching_payment(
    client, admin_staff_token, seeded_customer, db_session
):
    integration_id = await _create_stripe_integration(client, admin_staff_token)

    async with get_sessionmaker()() as session:
        payment = Payment(
            order_id=seeded_customer["order_id"],
            customer_id=seeded_customer["customer_id"],
            status="pending",
            amount=42.0,
            gateway="stripe",
            gateway_payment_intent_id="pi_webhook_test_2",
        )
        session.add(payment)
        await session.commit()
        payment_id = payment.id

    payload = {
        "id": "evt_2",
        "type": "payment_intent.payment_failed",
        "data": {"object": {"id": "pi_webhook_test_2", "status": "requires_payment_method"}},
    }
    body = json.dumps(payload).encode()

    response = await client.post(
        f"/api/v1/webhooks/stripe/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body, "whsec_test")},
    )

    assert response.status_code == 200, response.text

    async with get_sessionmaker()() as session:
        reloaded = await session.get(Payment, payment_id)
        assert reloaded is not None
        assert reloaded.status == "failed"


@pytest.mark.asyncio
async def test_refund_updated_marks_the_refund_completed(
    client, admin_staff_token, seeded_customer, db_session
):
    integration_id = await _create_stripe_integration(client, admin_staff_token)

    async with get_sessionmaker()() as session:
        refund = RefundRequest(
            order_id=seeded_customer["order_id"],
            customer_id=seeded_customer["customer_id"],
            amount=20.0,
            status="approved",
            reason="test",
            idempotency_key="idem_webhook_test",
            gateway="stripe",
            gateway_reference="re_webhook_test_1",
        )
        session.add(refund)
        await session.commit()
        refund_id = refund.id

    payload = {
        "id": "evt_3",
        "type": "refund.updated",
        "data": {"object": {"id": "re_webhook_test_1", "status": "succeeded"}},
    }
    body = json.dumps(payload).encode()

    response = await client.post(
        f"/api/v1/webhooks/stripe/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body, "whsec_test")},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "handled": True}

    async with get_sessionmaker()() as session:
        reloaded = await session.get(RefundRequest, refund_id)
        assert reloaded is not None
        assert reloaded.status == "completed"


@pytest.mark.asyncio
async def test_unhandled_event_type_is_acknowledged_without_error(client, admin_staff_token):
    integration_id = await _create_stripe_integration(client, admin_staff_token)
    payload = {"id": "evt_4", "type": "customer.created", "data": {"object": {}}}
    body = json.dumps(payload).encode()

    response = await client.post(
        f"/api/v1/webhooks/stripe/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body, "whsec_test")},
    )

    assert response.status_code == 200
    assert response.json() == {"received": True, "handled": False}


@pytest.mark.asyncio
async def test_bad_signature_is_rejected(client, admin_staff_token):
    integration_id = await _create_stripe_integration(client, admin_staff_token)
    body = json.dumps({"id": "evt_5", "type": "payment_intent.succeeded", "data": {}}).encode()

    response = await client.post(
        f"/api/v1/webhooks/stripe/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": "t=123,v1=not-real"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unknown_integration_id_is_rejected(client):
    body = json.dumps({"id": "evt_6", "type": "payment_intent.succeeded", "data": {}}).encode()

    response = await client.post(
        "/api/v1/webhooks/stripe/does-not-exist",
        content=body,
        headers={"Content-Type": "application/json", "Stripe-Signature": _sign(body, "whsec_test")},
    )

    assert response.status_code == 401
