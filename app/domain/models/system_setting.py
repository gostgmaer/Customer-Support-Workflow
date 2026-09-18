from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, new_uuid


class SystemSetting(Base, TimestampMixin, TenantScopedMixin):
    """Per-tenant runtime setting override (spec §32/§43): a small allow-list
    of operational tunables (`app.config.dynamic_settings.OVERRIDABLE_SETTINGS`)
    editable via `PUT/DELETE /api/v1/admin/settings/{key}` without an env var
    change or redeploy. Never holds secrets - the allow-list is what keeps
    API keys/JWT_SECRET/DATABASE_URL out of this table (see docs/SECURITY.md)."""

    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_system_settings_tenant_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)  # JSON-encoded scalar
    updated_by: Mapped[str] = mapped_column(String(36), nullable=False)
