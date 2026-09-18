"""Customer self-service auth (register/login) - the real login flow the
frontend chat UI uses, as opposed to auth_token/create_access_token being
minted directly in tests/scripts.
"""

import uuid

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.security.auth import decode_access_token


@pytest.mark.asyncio
async def test_register_then_login_round_trips(client):
    email = f"newcustomer_{uuid.uuid4().hex[:8]}@example.com"
    register_response = await client.post(
        "/api/v1/customers/register",
        json={"email": email, "password": "a-strong-password-123", "full_name": "New Customer"},
    )
    assert register_response.status_code == 201
    register_body = register_response.json()
    assert register_body["access_token"]
    customer_id, tenant_id = decode_access_token(register_body["access_token"])
    assert customer_id == register_body["customer_id"]
    assert tenant_id == DEFAULT_TENANT_ID

    login_response = await client.post(
        "/api/v1/customers/login", json={"email": email, "password": "a-strong-password-123"}
    )
    assert login_response.status_code == 200
    assert login_response.json()["customer_id"] == register_body["customer_id"]


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client):
    email = f"dupe_{uuid.uuid4().hex[:8]}@example.com"
    body = {"email": email, "password": "a-strong-password-123", "full_name": "Dupe"}
    first = await client.post("/api/v1/customers/register", json=body)
    assert first.status_code == 201
    second = await client.post("/api/v1/customers/register", json=body)
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_login_fails_with_wrong_password(client, seeded_customer):
    response = await client.post(
        "/api/v1/customers/login",
        json={"email": seeded_customer["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_credentials(client, seeded_customer):
    response = await client.post(
        "/api/v1/customers/login",
        json={"email": seeded_customer["email"], "password": seeded_customer["password"]},
    )
    assert response.status_code == 200
    assert response.json()["customer_id"] == seeded_customer["customer_id"]


@pytest.mark.asyncio
async def test_login_fails_for_unknown_email(client):
    response = await client.post(
        "/api/v1/customers/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_the_authenticated_customer(client, auth_token, seeded_customer):
    response = await client.get("/api/v1/customers/me", headers={"Authorization": f"Bearer {auth_token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == seeded_customer["customer_id"]


@pytest.mark.asyncio
async def test_me_requires_a_customer_token(client, staff_token):
    response = await client.get("/api/v1/customers/me", headers={"Authorization": f"Bearer {staff_token}"})
    assert response.status_code == 401
