"""app.security.oauth2 (spec: Phase 10.4) - state sign/verify round-trip
and tamper detection, plus token exchange/refresh against a
respx-mocked token endpoint (this project's established HTTP-mocking
library). No real Google/Microsoft OAuth app exists to live-verify
against - see docs/ARCHITECTURE.md's "RAG doc connectors" for the
documented boundary.
"""

from __future__ import annotations

import time

import pytest
import respx
from httpx import Response

from app.domain.exceptions import AuthenticationError, IntegrationError
from app.security.oauth2 import (
    OAuthProviderConfig,
    build_authorize_url,
    exchange_code_for_tokens,
    refresh_access_token,
    sign_state,
    verify_state,
)

_PROVIDER = OAuthProviderConfig(
    authorize_url="https://accounts.example.com/authorize",
    token_url="https://accounts.example.com/token",
    client_id="client-123",
    client_secret="secret-abc",
    redirect_uri="https://app.example.com/api/v1/oauth/callback/google_drive",
    scopes=["scope-a", "scope-b"],
)


def test_sign_state_and_verify_state_round_trip():
    state = sign_state("int_123")
    assert verify_state(state) == "int_123"


def test_verify_state_rejects_a_tampered_signature():
    state = sign_state("int_123")
    payload_b64, _signature = state.split(".", 1)
    tampered = f"{payload_b64}.deadbeef"
    with pytest.raises(AuthenticationError):
        verify_state(tampered)


def test_verify_state_rejects_a_malformed_state():
    with pytest.raises(AuthenticationError):
        verify_state("not-a-valid-state")


def test_verify_state_rejects_an_expired_state(monkeypatch):
    state = sign_state("int_123")
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 1000)
    with pytest.raises(AuthenticationError):
        verify_state(state)


def test_build_authorize_url_includes_state_and_client_id():
    url = build_authorize_url(_PROVIDER, "some-state")
    assert url.startswith(_PROVIDER.authorize_url)
    assert "state=some-state" in url
    assert "client_id=client-123" in url


@respx.mock
async def test_exchange_code_for_tokens_returns_a_token_set():
    respx.post(_PROVIDER.token_url).mock(
        return_value=Response(
            200,
            json={"access_token": "at_1", "refresh_token": "rt_1", "expires_in": 3600},
        )
    )

    tokens = await exchange_code_for_tokens(_PROVIDER, "auth-code")

    assert tokens.access_token == "at_1"
    assert tokens.refresh_token == "rt_1"
    assert tokens.expires_at


@respx.mock
async def test_exchange_code_for_tokens_raises_on_error_response():
    respx.post(_PROVIDER.token_url).mock(return_value=Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(IntegrationError):
        await exchange_code_for_tokens(_PROVIDER, "bad-code")


@respx.mock
async def test_refresh_access_token_returns_a_fresh_token_set():
    respx.post(_PROVIDER.token_url).mock(
        return_value=Response(200, json={"access_token": "at_2", "expires_in": 3600})
    )

    tokens = await refresh_access_token(_PROVIDER, "rt_1")

    assert tokens.access_token == "at_2"
    # Google/Microsoft commonly omit refresh_token on a refresh response
    # (it's unchanged) - the original must be preserved, not lost.
    assert tokens.refresh_token == "rt_1"


@respx.mock
async def test_refresh_access_token_raises_on_error_response():
    respx.post(_PROVIDER.token_url).mock(return_value=Response(401, json={"error": "invalid_grant"}))

    with pytest.raises(IntegrationError):
        await refresh_access_token(_PROVIDER, "revoked-token")
