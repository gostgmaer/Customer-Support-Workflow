"""POST /api/v1/webhooks/storefront/{integration_id} (spec: Phase 8.4,
timestamped/replay-protected signature scheme added in Phase 10.1) -
the one inbound-authenticated route in this codebase (HMAC signature
against `Integration.config.webhook_secret`, not a staff JWT).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from app.db.session import get_sessionmaker


def _sign(secret: str, body: bytes) -> str:
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode() + body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


async def _create_integration(client, admin_staff_token, *, webhook_secret: str, enabled: bool = True) -> str:
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Webhook Test Storefront",
        "type": "openapi",
        "base_url": "https://storefront.example.com",
        "auth_type": "none",
        "credentials": {},
        "config": {
            "spec_url": "https://storefront.example.com/openapi.json",
            "webhook_secret": webhook_secret,
        },
        "enabled": enabled,
    }
    response = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_valid_signature_with_no_correlation_is_acknowledged_without_a_ticket(
    client, admin_staff_token
):
    integration_id = await _create_integration(client, admin_staff_token, webhook_secret="shh")
    payload = {"event": "order.refunded", "order_id": "ORD-does-not-exist", "data": {}}
    body = json.dumps(payload).encode()

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": _sign("shh", body)},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"received": True, "correlated": False}


@pytest.mark.asyncio
async def test_bad_signature_is_rejected(client, admin_staff_token):
    integration_id = await _create_integration(client, admin_staff_token, webhook_secret="shh")
    body = json.dumps({"event": "order.refunded", "order_id": "ORD-1", "data": {}}).encode()

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": "not-the-real-signature"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_signature_is_rejected(client, admin_staff_token):
    integration_id = await _create_integration(client, admin_staff_token, webhook_secret="shh")
    body = json.dumps({"event": "order.refunded", "order_id": "ORD-1", "data": {}}).encode()

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unknown_integration_id_is_rejected(client):
    body = json.dumps({"event": "order.refunded", "order_id": "ORD-1", "data": {}}).encode()

    response = await client.post(
        "/api/v1/webhooks/storefront/does-not-exist",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": _sign("shh", body)},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_disabled_integration_is_rejected(client, admin_staff_token):
    integration_id = await _create_integration(
        client, admin_staff_token, webhook_secret="shh", enabled=False
    )
    body = json.dumps({"event": "order.refunded", "order_id": "ORD-1", "data": {}}).encode()

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": _sign("shh", body)},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correlated_event_creates_a_ticket_on_the_matching_conversation(
    client, admin_staff_token, seeded_customer, seeded_workflow_run
):
    integration_id = await _create_integration(client, admin_staff_token, webhook_secret="shh")

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        from app.domain.models import Conversation

        conversation = await session.get(Conversation, seeded_workflow_run["conversation_id"])
        conversation.metadata_json = {"last_order_id": "ORD-42"}
        await session.commit()

    payload = {"event": "order.shipped", "order_id": "ORD-42", "data": {"carrier": "FastShip"}}
    body = json.dumps(payload).encode()

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": _sign("shh", body)},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["correlated"] is True
    assert result["ticket_id"]

    admin_headers = {"Authorization": f"Bearer {admin_staff_token}"}
    ticket_resp = await client.get(f"/api/v1/support/tickets/{result['ticket_id']}", headers=admin_headers)
    assert ticket_resp.status_code == 200
    ticket = ticket_resp.json()
    assert ticket["intent"] == "WEBHOOK"
    assert ticket["priority"] == "LOW"
    assert ticket["conversation_id"] == seeded_workflow_run["conversation_id"]
    assert "order.shipped" in ticket["summary"]


@pytest.mark.asyncio
async def test_stale_timestamp_is_rejected(client, admin_staff_token):
    """spec: Phase 10.1 - a signature that's otherwise valid but whose
    timestamp is outside the replay-tolerance window must be rejected,
    closing the gap the original Phase 8.4 scheme left open."""
    integration_id = await _create_integration(client, admin_staff_token, webhook_secret="shh")
    body = json.dumps({"event": "order.refunded", "order_id": "ORD-1", "data": {}}).encode()
    old_timestamp = int(time.time()) - 1000
    signed_payload = f"{old_timestamp}.".encode() + body
    signature = hmac.new(b"shh", signed_payload, hashlib.sha256).hexdigest()
    stale_header = f"t={old_timestamp},v1={signature}"

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": stale_header},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_integration_with_no_webhook_secret_configured_rejects_everything(
    client, admin_staff_token
):
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body_req = {
        "name": "No Secret Storefront",
        "type": "openapi",
        "base_url": "https://storefront.example.com",
        "auth_type": "none",
        "credentials": {},
        "config": {"spec_url": "https://storefront.example.com/openapi.json"},
    }
    create_resp = await client.post("/api/v1/admin/integrations", json=body_req, headers=headers)
    integration_id = create_resp.json()["id"]
    body = json.dumps({"event": "order.refunded", "order_id": "ORD-1", "data": {}}).encode()

    response = await client.post(
        f"/api/v1/webhooks/storefront/{integration_id}",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": _sign("anything", body)},
    )

    assert response.status_code == 401
