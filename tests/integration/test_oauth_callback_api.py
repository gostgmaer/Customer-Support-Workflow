"""GET /api/v1/oauth/callback/{provider} (spec: Phase 10.4) - the second
genuinely unauthenticated route in this codebase alongside the inbound
webhooks (tests/integration/test_webhooks_api.py), authenticated instead
by a CSRF-safe, HMAC-signed `state` parameter
(app.security.oauth2.sign_state/verify_state).
"""

from __future__ import annotations

import respx
from httpx import Response

from app.db.session import get_sessionmaker
from app.domain.models import Integration
from app.security.oauth2 import sign_state


async def _create_google_drive_integration(client, admin_staff_token) -> str:
    headers = {"Authorization": f"Bearer {admin_staff_token}"}
    body = {
        "name": "Callback Test Google Drive",
        "type": "docs",
        "base_url": "https://www.googleapis.com",
        "auth_type": "oauth2",
        "credentials": {},
        "config": {"provider": "google_drive", "folder_id": "folder-123"},
    }
    response = await client.post("/api/v1/admin/integrations", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_valid_state_exchanges_the_code_and_stores_credentials(client, admin_staff_token):
    integration_id = await _create_google_drive_integration(client, admin_staff_token)
    state = sign_state(integration_id)

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(
                200, json={"access_token": "at_real", "refresh_token": "rt_real", "expires_in": 3600}
            )
        )
        response = await client.get(
            f"/api/v1/oauth/callback/google_drive?code=auth-code-123&state={state}"
        )

    assert response.status_code in (302, 307)

    async with get_sessionmaker()() as session:
        integration = await session.get(Integration, integration_id)
        assert integration is not None
        from app.integrations.base import get_credentials

        creds = get_credentials(integration)
        assert creds["access_token"] == "at_real"
        assert creds["refresh_token"] == "rt_real"
        assert creds["expires_at"]


async def test_tampered_state_is_rejected(client, admin_staff_token):
    integration_id = await _create_google_drive_integration(client, admin_staff_token)
    state = sign_state(integration_id)
    tampered = state.rsplit(".", 1)[0] + ".0000000000000000000000000000000000000000000000000000000000000000"

    response = await client.get(f"/api/v1/oauth/callback/google_drive?code=auth-code-123&state={tampered}")

    assert response.status_code == 401


async def test_malformed_state_is_rejected(client):
    response = await client.get(
        "/api/v1/oauth/callback/google_drive?code=auth-code-123&state=not-a-real-state"
    )

    assert response.status_code == 401


async def test_unknown_integration_id_in_state_is_rejected(client):
    state = sign_state("does-not-exist")

    response = await client.get(f"/api/v1/oauth/callback/google_drive?code=auth-code-123&state={state}")

    assert response.status_code == 401


async def test_token_exchange_failure_surfaces_as_an_error(client, admin_staff_token):
    integration_id = await _create_google_drive_integration(client, admin_staff_token)
    state = sign_state(integration_id)

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )
        response = await client.get(
            f"/api/v1/oauth/callback/google_drive?code=bad-code&state={state}"
        )

    assert response.status_code >= 400
