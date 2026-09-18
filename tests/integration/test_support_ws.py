"""GET /api/v1/support/ws/conversations/{conversation_id} (spec: Phase
10.3) - the customer-side realtime push channel. Uses Starlette's
TestClient.websocket_connect (httpx's ASGITransport, used by this
project's usual async `client` fixture, does not support the websocket
scope) - a plain sync test, seeding data via asyncio.run rather than the
usual async pytest fixtures, to avoid mixing a running pytest-asyncio
event loop with TestClient's own internal thread portal.
"""

from __future__ import annotations

import asyncio
import uuid

from starlette.testclient import TestClient

from app.db.base import DEFAULT_TENANT_ID
from app.db.session import get_sessionmaker, init_models
from app.domain.models import Conversation, Customer
from app.main import app
from app.security.auth import create_access_token
from app.security.passwords import hash_password


def _seed_customer_and_conversation() -> tuple[str, str, str]:
    async def _seed() -> tuple[str, str, str]:
        await init_models()
        customer_id = f"cust_{uuid.uuid4().hex[:8]}"
        conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
        async with get_sessionmaker()() as session:
            session.add(
                Customer(
                    id=customer_id,
                    email=f"{customer_id}@example.com",
                    full_name="WS Test Customer",
                    password_hash=hash_password("irrelevant-for-this-test"),
                )
            )
            await session.flush()
            session.add(
                Conversation(
                    id=conversation_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    customer_id=customer_id,
                    channel="web",
                    status="open",
                )
            )
            await session.commit()
        token = create_access_token(customer_id)
        return customer_id, conversation_id, token

    return asyncio.run(_seed())


def test_valid_token_and_owned_conversation_connects_and_receives_a_broadcast():
    _customer_id, conversation_id, token = _seed_customer_and_conversation()
    client = TestClient(app)

    with client.websocket_connect(f"/api/v1/support/ws/conversations/{conversation_id}?token={token}") as ws:
        from app.realtime.connections import get_connection_manager

        asyncio.run(
            get_connection_manager().broadcast(
                conversation_id, {"event": "order.shipped", "order_id": "ORD-1", "ticket_id": "t1"}
            )
        )
        message = ws.receive_json()
        assert message == {"event": "order.shipped", "order_id": "ORD-1", "ticket_id": "t1"}


def test_wrong_customers_token_is_rejected():
    _customer_id, conversation_id, _token = _seed_customer_and_conversation()
    _other_customer_id, _other_conversation_id, other_token = _seed_customer_and_conversation()
    client = TestClient(app)

    try:
        with client.websocket_connect(
            f"/api/v1/support/ws/conversations/{conversation_id}?token={other_token}"
        ):
            raise AssertionError("expected the connection to be rejected")
    except Exception:  # noqa: BLE001 - starlette raises WebSocketDisconnect on a rejected handshake
        pass


def test_garbage_token_is_rejected():
    _customer_id, conversation_id, _token = _seed_customer_and_conversation()
    client = TestClient(app)

    try:
        with client.websocket_connect(
            f"/api/v1/support/ws/conversations/{conversation_id}?token=not-a-real-token"
        ):
            raise AssertionError("expected the connection to be rejected")
    except Exception:  # noqa: BLE001
        pass


def test_unknown_conversation_is_rejected():
    _customer_id, _conversation_id, token = _seed_customer_and_conversation()
    client = TestClient(app)

    try:
        with client.websocket_connect(f"/api/v1/support/ws/conversations/does-not-exist?token={token}"):
            raise AssertionError("expected the connection to be rejected")
    except Exception:  # noqa: BLE001
        pass
