"""OAuth2 authorization-code callback (spec: Phase 10.4) - a genuinely
unauthenticated route, a third distinct inbound-auth story in this
codebase alongside staff JWTs and HMAC-signed webhooks
(app.api.routes.webhooks): the caller here is a browser redirect from
Google/Microsoft's own server, carrying no staff JWT at all.
Authenticated instead by a CSRF-safe, HMAC-signed `state` parameter
(app.security.oauth2.sign_state/verify_state), set when an admin clicked
"Connect" via the staff-authenticated
`GET /admin/integrations/{id}/oauth/authorize` route in
app.api.routes.integrations.

Mounted directly in app.main, not nested inside integrations.py's
RequireAdmin-wrapped router - every dependency in that router assumes a
staff JWT, which this redirect never carries.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.domain.exceptions import AuthenticationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.observability.logging import get_logger
from app.security.oauth2 import exchange_code_for_tokens, provider_config_for, verify_state

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/oauth", tags=["oauth"])


@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    integration_id = verify_state(state)

    # Cross-tenant lookup, deliberately - same posture as the inbound
    # webhook routes (app.api.routes.webhooks): the redirect carries no
    # tenant concept at all, only what the signed state names.
    integration = await session.get(Integration, integration_id)
    if integration is None:
        raise AuthenticationError("Unknown integration for this OAuth2 callback")

    provider_config = provider_config_for(provider)
    tokens = await exchange_code_for_tokens(provider_config, code)

    integration.encrypted_credentials = encode_credentials(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token or "",
            "expires_at": tokens.expires_at,
        }
    )
    await session.commit()
    logger.info("oauth_callback_succeeded", integration_id=integration_id, provider=provider)

    frontend_base = get_settings().cors_allowed_origins[0]
    return RedirectResponse(f"{frontend_base}/admin/integrations?connected={integration_id}")
