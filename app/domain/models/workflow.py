from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, new_uuid


class WorkflowRun(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), index=True
    )
    message_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(30), default="running")  # running|completed|failed|escalated
    final_response: Mapped[str | None] = mapped_column(String, nullable=True)
    requires_human: Mapped[bool] = mapped_column(default=False)
    response_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)


class WorkflowEvent(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "workflow_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_runs.id"), index=True
    )
    node_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # started|succeeded|failed
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
