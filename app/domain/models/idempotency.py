from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin


class IdempotencyKey(Base, TimestampMixin, TenantScopedMixin):
    """Backs app.services.idempotency (spec §20).

    key = f"{conversation_id}:{action}:{request_id}". A second request with
    the same key returns `response` instead of re-executing the action.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    action: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")  # in_progress|completed
    response: Mapped[dict] = mapped_column(JSON, default=dict)
