"""OAuth2 authorization-code + refresh-token support (spec: Phase 10.4),
used only by the Google Drive / SharePoint docs connectors - every other
integration in this codebase (JIRA/WooCommerce/MCP/OpenAPI/Confluence/
Notion/Stripe) uses a static, non-expiring credential (api_key/bearer/
basic), so this is the first genuine "credentials expire and must be
refreshed" case this app has had.

`sign_state`/`verify_state` are a small, dedicated HMAC-signed blob
(reusing this codebase's existing `hmac`/`secrets` primitives - see
`app.security.webhooks`) rather than routed through `app.security.auth`'s
JWT machinery: a `state` value has no "customer"/"staff"/"system" scope
concept, so a fourth JWT scope would be more disruptive to add than this
small, purpose-built helper.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.domain.exceptions import AuthenticationError, IntegrationError

_STATE_TOLERANCE_SECONDS = 600  # 10 minutes - generous enough for a real admin login/consent flow
_TIMEOUT_SECONDS = 10.0


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: str  # ISO 8601 - stored alongside the tokens in Integration.encrypted_credentials


@dataclass
class OAuthProviderConfig:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str]


def google_provider_config() -> OAuthProviderConfig:
    settings = get_settings()
    return OAuthProviderConfig(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        redirect_uri=settings.google_oauth_redirect_uri,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )


def microsoft_provider_config() -> OAuthProviderConfig:
    settings = get_settings()
    tenant = settings.microsoft_oauth_tenant_id
    return OAuthProviderConfig(
        authorize_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        client_id=settings.microsoft_oauth_client_id,
        client_secret=settings.microsoft_oauth_client_secret,
        redirect_uri=settings.microsoft_oauth_redirect_uri,
        scopes=["https://graph.microsoft.com/Files.Read.All", "offline_access"],
    )


def provider_config_for(provider: str) -> OAuthProviderConfig:
    if provider == "google_drive":
        return google_provider_config()
    if provider == "sharepoint":
        return microsoft_provider_config()
    raise IntegrationError(f"No OAuth2 provider configuration for '{provider}'")


def build_authorize_url(provider: OAuthProviderConfig, state: str) -> str:
    params = {
        "client_id": provider.client_id,
        "redirect_uri": provider.redirect_uri,
        "response_type": "code",
        "scope": " ".join(provider.scopes),
        "state": state,
        # Google-specific, harmless elsewhere - without these, Google only
        # returns a refresh_token on the very first consent ever granted.
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


def _token_set_from_response(data: dict) -> TokenSet:
    expires_in = int(data.get("expires_in", 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at.isoformat(),
    )


async def exchange_code_for_tokens(provider: OAuthProviderConfig, code: str) -> TokenSet:
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(
            provider.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "redirect_uri": provider.redirect_uri,
            },
        )
    if response.status_code >= 400:
        raise IntegrationError(
            f"OAuth2 token exchange failed ({response.status_code}): {response.text[:200]}"
        )
    return _token_set_from_response(response.json())


async def refresh_access_token(provider: OAuthProviderConfig, refresh_token: str) -> TokenSet:
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(
            provider.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
            },
        )
    if response.status_code >= 400:
        raise IntegrationError(f"OAuth2 token refresh failed ({response.status_code}): {response.text[:200]}")
    token_set = _token_set_from_response(response.json())
    if token_set.refresh_token is None:
        # A refresh response commonly omits refresh_token (it's unchanged) -
        # keep the one we already had rather than losing it.
        token_set.refresh_token = refresh_token
    return token_set


def sign_state(integration_id: str) -> str:
    settings = get_settings()
    payload = {"integration_id": integration_id, "nonce": secrets.token_hex(8), "ts": int(time.time())}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    signature = hmac.new(settings.jwt_secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_state(state: str) -> str:
    """Returns the integration_id the state was signed for, or raises
    AuthenticationError on a tampered, malformed, or stale (>10min) state."""
    settings = get_settings()
    try:
        payload_b64, signature = state.split(".", 1)
    except ValueError as exc:
        raise AuthenticationError("Malformed OAuth2 state parameter") from exc

    expected = hmac.new(settings.jwt_secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise AuthenticationError("Invalid OAuth2 state parameter")

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Malformed OAuth2 state parameter") from exc

    if abs(time.time() - payload.get("ts", 0)) > _STATE_TOLERANCE_SECONDS:
        raise AuthenticationError("OAuth2 state parameter has expired")

    integration_id = payload.get("integration_id")
    if not integration_id:
        raise AuthenticationError("OAuth2 state parameter missing integration_id")
    return integration_id
