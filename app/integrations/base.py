from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import IntegrationError
from app.domain.models import Integration
from app.integrations.crypto import decrypt_secret, encrypt_secret

_TIMEOUT_SECONDS = 10.0


def get_credentials(integration: Integration) -> dict[str, str]:
    try:
        return json.loads(decrypt_secret(integration.encrypted_credentials))
    except json.JSONDecodeError as exc:
        raise IntegrationError(f"Integration '{integration.name}' has corrupted credentials") from exc


async def ensure_fresh_oauth2_token(integration: Integration, session: AsyncSession) -> None:
    """Refreshes `integration`'s OAuth2 access token if expired (spec:
    Phase 10.4) - the first credential in this codebase that actually
    expires; every other auth_type (api_key/bearer/basic) is a static,
    non-expiring value, so nothing else needs this. Must be called
    *before* `build_http_client` for an `auth_type == "oauth2"`
    integration - `build_http_client` itself stays synchronous (used in
    an `async with` at every existing call site) and just reads whatever
    `access_token` is currently stored, unrefreshed.

    Mutates `integration.encrypted_credentials` **in memory only** on a
    refresh, mirroring how `app.integrations.health`'s openapi/mcp
    branches already mutate `integration.config` in memory and leave
    committing to the already-session-holding caller - this function
    never commits `session` itself.
    """
    if integration.auth_type != "oauth2":
        return

    creds = get_credentials(integration)
    try:
        expires_at = datetime.fromisoformat(creds.get("expires_at", ""))
    except ValueError:
        expires_at = datetime.now(UTC)

    if datetime.now(UTC) < expires_at:
        return

    from app.security.oauth2 import provider_config_for, refresh_access_token

    provider_config = provider_config_for(integration.config.get("provider", ""))
    refreshed = await refresh_access_token(provider_config, creds.get("refresh_token", ""))
    integration.encrypted_credentials = encode_credentials(
        {
            "access_token": refreshed.access_token,
            "refresh_token": refreshed.refresh_token or "",
            "expires_at": refreshed.expires_at,
        }
    )
    _ = session  # the caller commits this mutation - matches this codebase's in-memory-mutation convention


def build_http_client(integration: Integration) -> httpx.AsyncClient:
    """One `httpx.AsyncClient` per call, configured for `integration`'s
    stored auth. `auth_type`:
    - `api_key`: sent as a header, name from `config.api_key_header`
      (default `Authorization`) - fits most vendor "X-Api-Key" schemes.
    - `bearer`: `Authorization: Bearer <token>` - credentials key `token`.
    - `basic`: HTTP basic auth - credentials keys `username`/`password`
      (JIRA Cloud: email + API token; WooCommerce: consumer_key +
      consumer_secret both fit this shape).
    - `oauth2` (spec: Phase 10.4, Google Drive/SharePoint docs connectors
      only): `Authorization: Bearer <access_token>` - the caller must
      call `ensure_fresh_oauth2_token(integration, session)` first if the
      token might be expired; this function only ever reads whatever is
      currently stored, it never refreshes (kept synchronous so every
      existing `async with build_http_client(integration) as client:`
      call site needs no change).
    - `none`: no auth header sent at all - some genuinely public APIs
      (live-verified: DeepWiki's MCP server, mcp.deepwiki.com) actively
      *reject* a request that carries any Authorization header, even an
      unused/placeholder one, rather than just ignoring it.
    """
    creds = get_credentials(integration)
    headers: dict[str, str] = {}
    auth: tuple[str, str] | None = None

    if integration.auth_type == "api_key":
        header_name = integration.config.get("api_key_header", "Authorization")
        headers[header_name] = creds.get("api_key", "")
    elif integration.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {creds.get('token', '')}"
    elif integration.auth_type == "basic":
        auth = (creds.get("username", ""), creds.get("password", ""))
    elif integration.auth_type == "oauth2":
        headers["Authorization"] = f"Bearer {creds.get('access_token', '')}"
    elif integration.auth_type != "none":
        raise IntegrationError(f"Unknown auth_type '{integration.auth_type}'")

    return httpx.AsyncClient(
        base_url=integration.base_url, headers=headers, auth=auth, timeout=_TIMEOUT_SECONDS
    )


def encode_credentials(credentials: dict[str, str]) -> str:
    return encrypt_secret(json.dumps(credentials))


def short_response_body(text: str, limit: int = 200) -> str:
    """Trims an HTTP error response for use in an error message/toast -
    a full HTML error page (a common 404/auth-failure response from a
    misconfigured base URL) is noise, not diagnostic information."""
    stripped = text.strip()
    if stripped.startswith("<"):
        return "(non-JSON response - check the base URL)"
    return stripped[:limit]
