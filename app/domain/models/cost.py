from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, new_uuid


class ModelRequest(Base, TimestampMixin, TenantScopedMixin):
    """One row per LLM call (spec §42: cost tracking by provider/model/
    workflow/node/environment)."""

    __tablename__ = "model_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    node_name: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
