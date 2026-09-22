"""Admin CRUD for external-system connections (spec: JIRA/WooCommerce/SMTP/
custom REST APIs - see app.integrations), plus the one staff-facing,
manually-triggered integration action: a WooCommerce order lookup. JIRA
auto-create/comment are not exposed as endpoints here - they're
deterministic hooks (app.integrations.hooks) fired from the ticket
lifecycle itself; `POST /support/tickets/{id}/jira` (in tickets.py) is the
manual "create it now" fallback.
"""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.integration import (
    CreateIntegrationRequest,
    IntegrationResponse,
    RotateWebhookSecretResponse,
    TestIntegrationResponse,
    UpdateIntegrationRequest,
    WooCommerceLookupRequest,
    WooCommerceOrderSummary,
)
from app.db.session import get_db
from app.domain.exceptions import ValidationError
from app.domain.models import Integration
from app.integrations.base import encode_credentials
from app.integrations.crypto import decrypt_secret
from app.integrations.health import test_connection
from app.integrations.woocommerce import WooCommerceClient
from app.rag.docs_ingest import sync_docs_integration
from app.repositories.integrations import IntegrationRepository
from app.security.auth import STAFF_ROLES, require_staff_role
from app.security.oauth2 import build_authorize_url, provider_config_for, sign_state

admin_router = APIRouter(prefix="/api/v1/admin/integrations", tags=["admin"])
support_router = APIRouter(prefix="/api/v1/support/integrations", tags=["integrations"])

RequireAdmin = Depends(require_staff_role("ADMIN"))
RequireAnyStaff = Depends(require_staff_role(*STAFF_ROLES))


def _to_response(integration: Integration) -> dict:
    try:
        credential_keys = sorted(json.loads(decrypt_secret(integration.encrypted_credentials)).keys())
    except Exception:  # noqa: BLE001 - undecryptable creds shouldn't break the list view
        credential_keys = []
    # config.webhook_secret (stripe, or any storefront-webhook-carrying
    # integration) is plain JSON, not Fernet-encrypted like credentials -
    # mask its presence the same way credential_keys masks encrypted_credentials,
    # rather than returning the real value on every GET/POST/PUT (spec:
    # Phase 10.1 - this used to leak in plaintext here).
    config = integration.config
    if config.get("webhook_secret"):
        config = {**config, "webhook_secret": True}
    return {
        "id": integration.id,
        "name": integration.name,
        "type": integration.type,
        "base_url": integration.base_url,
        "auth_type": integration.auth_type,
        "credential_keys": credential_keys,
        "config": config,
        "enabled": integration.enabled,
        "created_by": integration.created_by,
        "created_at": integration.created_at,
        "updated_at": integration.updated_at,
    }


@admin_router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> list[dict]:
    _admin_id, _role, tenant_id = admin
    integrations = await IntegrationRepository(session, tenant_id).list()
    return [_to_response(i) for i in integrations]


async def _ensure_single_storefront(
    repo: IntegrationRepository, *, config: dict, enabled: bool, exclude_id: str | None = None
) -> None:
    """spec: Phase 12 audit - at most one ENABLED integration may carry
    `config.role == "storefront"` per tenant. Previously unenforced:
    `app.agents.resolution._get_storefront_integration` does "first match
    wins" with no defined ordering across integrations, so which one
    actually handled a commerce request was effectively non-deterministic
    whenever two carried the role simultaneously - confirmed live in this
    environment (both a "Demo Storefront" and an "Acme Store" integration
    carried it at once). Enforced here, not in `CreateIntegrationRequest`'s
    Pydantic validator, since "is there already another one" needs a real
    DB query, not just this request's own body."""
    if config.get("role") != "storefront" or not enabled:
        return
    for existing in await repo.list():
        if existing.id == exclude_id:
            continue
        if existing.enabled and existing.config.get("role") == "storefront":
            raise ValidationError(
                f"Integration '{existing.name}' is already this tenant's storefront - disable it, "
                "or unset its config.role, before designating another one."
            )


@admin_router.post("", response_model=IntegrationResponse, status_code=201)
async def create_integration(
    body: CreateIntegrationRequest,
    session: AsyncSession = Depends(get_db),
    admin: tuple[str, str, str] = RequireAdmin,
) -> dict:
    admin_id, _role, tenant_id = admin
    repo = IntegrationRepository(session, tenant_id)
    if await repo.get_by_name(body.name) is not None:
        raise ValidationError(f"An integration named '{body.name}' already exists")
    await _ensure_single_storefront(repo, config=body.config, enabled=body.enabled)

    integration = Integration(
        name=body.name,
        type=body.type,
        base_url=body.base_url.rstrip("/"),
        auth_type=body.auth_type,
        encrypted_credentials=encode_credentials(body.credentials),
        config=body.config,
        enabled=body.enabled,
        created_by=admin_id,
    )
    created = await repo.create(integration)
    await session.commit()
    return _to_response(created)


@admin_router.put("/{integration_id}", response_model=IntegrationResponse)
async def update_integration(
    integration_id: str,
    body: UpdateIntegrationRequest,
    session: AsyncSession = Depends(get_db),
    admin: tuple[str, str, str] = RequireAdmin,
) -> dict:
    _admin_id, _role, tenant_id = admin
    repo = IntegrationRepository(session, tenant_id)
    integration = await repo.get(integration_id)
    if integration is None:
        raise ValidationError(f"Integration {integration_id} not found")

    effective_config = body.config if body.config is not None else integration.config
    effective_enabled = body.enabled if body.enabled is not None else integration.enabled
    await _ensure_single_storefront(
        repo, config=effective_config, enabled=effective_enabled, exclude_id=integration.id
    )

    if body.name is not None:
        integration.name = body.name
    if body.base_url is not None:
        integration.base_url = body.base_url.rstrip("/")
    if body.auth_type is not None:
        integration.auth_type = body.auth_type
    if body.credentials is not None:
        integration.encrypted_credentials = encode_credentials(body.credentials)
    if body.config is not None:
        integration.config = body.config
    if body.enabled is not None:
        integration.enabled = body.enabled

    await session.commit()
    return _to_response(integration)


@admin_router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: str, session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> None:
    _admin_id, _role, tenant_id = admin
    repo = IntegrationRepository(session, tenant_id)
    integration = await repo.get(integration_id)
    if integration is None:
        raise ValidationError(f"Integration {integration_id} not found")
    await repo.delete(integration)
    await session.commit()


@admin_router.post("/{integration_id}/test", response_model=TestIntegrationResponse)
async def test_integration(
    integration_id: str, session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> dict:
    _admin_id, _role, tenant_id = admin
    integration = await IntegrationRepository(session, tenant_id).get(integration_id)
    if integration is None:
        raise ValidationError(f"Integration {integration_id} not found")
    ok, message = await test_connection(integration, session=session)
    if ok:
        # Only the openapi branch of test_connection mutates `integration`
        # (caching the freshly-parsed spec into config.spec_cache) - this
        # commit is a no-op for every other integration type.
        await session.commit()
    return {"ok": ok, "message": message}


@admin_router.post("/{integration_id}/sync")
async def sync_integration(
    integration_id: str, session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> dict:
    """spec: Phase 9.3 - manually-triggered sync for a `"docs"`
    integration (Confluence/Notion) into the knowledge base. No
    scheduler exists anywhere in this codebase, so this is the whole
    sync mechanism - not a placeholder for one - see
    app.rag.docs_ingest's module docstring."""
    _admin_id, _role, tenant_id = admin
    integration = await IntegrationRepository(session, tenant_id).get(integration_id)
    if integration is None:
        raise ValidationError(f"Integration {integration_id} not found")
    if integration.type != "docs":
        raise ValidationError(f"Integration {integration_id} is not a 'docs' integration")
    chunks_ingested = await sync_docs_integration(integration, session, tenant_id=tenant_id)
    return {"chunks_ingested": chunks_ingested}


@admin_router.post("/{integration_id}/rotate-webhook-secret", response_model=RotateWebhookSecretResponse)
async def rotate_webhook_secret(
    integration_id: str, session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> dict:
    """spec: Phase 10.1 - generates a fresh `config.webhook_secret`
    instead of an admin hand-typing one into PUT .../{id}. Not restricted
    to any particular integration type - harmless to call on one that
    doesn't currently use a webhook route. The real value is returned
    here, once; every other response masks it (see `_to_response`)."""
    _admin_id, _role, tenant_id = admin
    integration = await IntegrationRepository(session, tenant_id).get(integration_id)
    if integration is None:
        raise ValidationError(f"Integration {integration_id} not found")
    new_secret = secrets.token_hex(32)
    integration.config = {**integration.config, "webhook_secret": new_secret}
    await session.commit()
    return {"webhook_secret": new_secret}


@admin_router.get("/{integration_id}/oauth/authorize")
async def authorize_oauth_integration(
    integration_id: str, session: AsyncSession = Depends(get_db), admin: tuple[str, str, str] = RequireAdmin
) -> RedirectResponse:
    """spec: Phase 10.4 - admin-initiated, staff-authenticated (unlike
    /api/v1/oauth/callback/{provider} in app.api.routes.oauth_callback,
    which is genuinely unauthenticated - the browser redirect back from
    this URL carries no staff JWT). Redirects to Google/Microsoft's own
    consent screen with a signed `state` naming this integration."""
    _admin_id, _role, tenant_id = admin
    integration = await IntegrationRepository(session, tenant_id).get(integration_id)
    if integration is None:
        raise ValidationError(f"Integration {integration_id} not found")
    provider = integration.config.get("provider")
    if provider not in {"google_drive", "sharepoint"}:
        raise ValidationError(
            f"Integration {integration_id} has no OAuth2 provider configured (config.provider="
            f"{provider!r}, expected 'google_drive' or 'sharepoint')"
        )
    provider_config = provider_config_for(provider)
    state = sign_state(integration_id)
    return RedirectResponse(build_authorize_url(provider_config, state))


@support_router.post("/woocommerce/lookup", response_model=WooCommerceOrderSummary | None)
async def lookup_woocommerce_order(
    body: WooCommerceLookupRequest,
    session: AsyncSession = Depends(get_db),
    staff: tuple[str, str, str] = RequireAnyStaff,
) -> dict | None:
    """Staff-triggered only - see app.integrations.woocommerce's module
    docstring for why this isn't offered to the AI as an autonomous tool."""
    _staff_id, _role, tenant_id = staff
    integration = await IntegrationRepository(session, tenant_id).get_enabled_by_type("woocommerce")
    if integration is None:
        raise ValidationError("No enabled WooCommerce integration is configured for this tenant")
    order = await WooCommerceClient(integration).find_order(body.order_number)
    if order is None:
        return None
    return {
        "id": order.get("id"),
        "number": str(order.get("number", order.get("id", ""))),
        "status": order.get("status", "unknown"),
        "total": str(order.get("total", "0")),
        "currency": order.get("currency", ""),
        "date_created": order.get("date_created", ""),
    }
