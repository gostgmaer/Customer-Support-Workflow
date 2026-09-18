from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, new_uuid


class StaffUser(Base, TimestampMixin, TenantScopedMixin):
    """A human support agent/admin (spec §18/§26: ticket approve/reject is a
    distinct trust boundary from the customer-facing API - see
    docs/SECURITY.md). Real deployments should back this with SSO/an
    identity provider instead of local password auth; this is a minimal
    but real implementation, not a placeholder static token.
    """

    __tablename__ = "staff_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))  # support_agent | support_admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
