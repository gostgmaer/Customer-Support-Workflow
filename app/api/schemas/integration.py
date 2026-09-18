from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

_TYPE_PATTERN = r"^(jira|woocommerce|smtp|custom|mcp|openapi|docs|stripe)$"
_AUTH_PATTERN = r"^(api_key|bearer|basic|none|oauth2)$"


class CreateIntegrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern=_TYPE_PATTERN)
    base_url: str = Field(min_length=1, max_length=500)
    auth_type: str = Field(pattern=_AUTH_PATTERN)
    credentials: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_type_specific_requirements(self) -> CreateIntegrationRequest:
        # Fail at creation time, not the first time app.integrations.jira.JiraClient
        # is constructed for a real auto-create/comment/test call.
        if self.type == "jira" and not self.config.get("project_key"):
            raise ValueError("JIRA integrations require config.project_key")
        if self.type == "mcp" and self.auth_type == "basic":
            # The MCP client (app.integrations.mcp_client) sends auth as an
            # HTTP header on the Streamable HTTP transport - basic auth's
            # username/password pair doesn't map onto that the way it does
            # for build_http_client's REST calls, so it's simplest to just
            # not support it here rather than silently mis-authenticate.
            raise ValueError("MCP integrations support api_key, bearer, or none auth only, not basic")
        if self.type == "openapi" and not (self.config.get("spec_url") or self.config.get("spec_inline")):
            # Some real OpenAPI specs aren't published at a stable URL an
            # admin can point at - support pasting the spec directly too,
            # but require at least one source rather than silently having
            # nothing to discover operations from.
            raise ValueError("openapi integrations require config.spec_url or config.spec_inline")
        if self.type == "docs":
            # spec: Phase 9.3 (Confluence/Notion) + Phase 10.4 (Google
            # Drive/SharePoint, OAuth2) - app.integrations.docs_connector.get_docs_client
            # dispatches on config.provider; each provider needs its own
            # "what to sync" identifier, at least one of which is required
            # (mirroring openapi's spec_url/spec_inline "at least one
            # source" pattern above).
            provider = self.config.get("provider")
            valid_providers = {"confluence", "notion", "google_drive", "sharepoint"}
            if provider not in valid_providers:
                raise ValueError(
                    "docs integrations require config.provider to be one of: "
                    + ", ".join(sorted(valid_providers))
                )
            if provider == "confluence" and not (self.config.get("space_key") or self.config.get("page_ids")):
                raise ValueError("Confluence docs integrations require config.space_key or config.page_ids")
            if provider == "notion" and not (self.config.get("database_id") or self.config.get("page_ids")):
                raise ValueError("Notion docs integrations require config.database_id or config.page_ids")
            if provider == "google_drive" and not (
                self.config.get("folder_id") or self.config.get("file_ids")
            ):
                raise ValueError(
                    "Google Drive docs integrations require config.folder_id or config.file_ids"
                )
            if provider == "sharepoint" and not self.config.get("drive_id"):
                raise ValueError("SharePoint docs integrations require config.drive_id")
        if self.type == "stripe" and not self.config.get("webhook_secret"):
            # spec: Phase 9.4 - required up front, same as the storefront
            # webhook integration's config.webhook_secret requirement (see
            # app.api.routes.webhooks) - Stripe's webhook is how a
            # refund's real outcome is confirmed, not optional polish.
            raise ValueError("stripe integrations require config.webhook_secret")
        return self


class UpdateIntegrationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    auth_type: str | None = Field(default=None, pattern=_AUTH_PATTERN)
    credentials: dict[str, str] | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class IntegrationResponse(BaseModel):
    id: str
    name: str
    type: str
    base_url: str
    auth_type: str
    # Which credential fields are set (e.g. ["api_key"]) - never the values.
    credential_keys: list[str]
    config: dict[str, Any]
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class TestIntegrationResponse(BaseModel):
    ok: bool
    message: str


class RotateWebhookSecretResponse(BaseModel):
    """The freshly-generated secret, in plaintext - returned exactly once,
    by this endpoint alone (spec: Phase 10.1). Every other integration
    response masks `config.webhook_secret` down to a boolean - see
    `app.api.routes.integrations._to_response`."""

    webhook_secret: str


class WooCommerceLookupRequest(BaseModel):
    order_number: str = Field(min_length=1, max_length=100)


class WooCommerceOrderSummary(BaseModel):
    id: int
    number: str
    status: str
    total: str
    currency: str
    date_created: str
