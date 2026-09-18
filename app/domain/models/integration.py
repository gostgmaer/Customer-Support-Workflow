from __future__ import annotations

from sqlalchemy import JSON, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, new_uuid


class Integration(Base, TimestampMixin, TenantScopedMixin):
    """A connection to an external system (JIRA, WooCommerce, SMTP, an MCP
    server, an OpenAPI/Swagger-described REST API, or any other REST API)
    - see app.integrations. `encrypted_credentials` is a Fernet-encrypted
    JSON blob (app.integrations.crypto); it is never decrypted anywhere
    except immediately before making the outbound call, and never
    returned by the admin API (see app.api.schemas.integration)."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_integrations_tenant_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # jira | woocommerce | smtp | custom | mcp | openapi
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False)  # api_key | basic | bearer
    encrypted_credentials: Mapped[str] = mapped_column(String(2000), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
