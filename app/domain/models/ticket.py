from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UTCDateTime, new_uuid


class SupportTicket(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), index=True
    )
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    intent: Mapped[str] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    summary: Mapped[str] = mapped_column(Text)
    customer_problem: Mapped[str] = mapped_column(Text)
    actions_taken: Mapped[list] = mapped_column(JSON, default=list)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    relevant_documents: Mapped[list] = mapped_column(JSON, default=list)
    reason_for_escalation: Mapped[str] = mapped_column(Text)
    recommended_next_action: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Set when a JIRA issue has been created for this ticket (auto on
    # escalation, or manually via POST .../jira) - see app.integrations.jira.
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Populated only for an external-tool-call ticket (spec: Phase 8.2) -
    # {"integration_name", "tool_name", "arguments"}, mirroring the subset
    # of app.workflow.state.SupportState's `pending_mcp_call` shown to
    # staff. None for a refund ticket - see app.workflow.runner.run_workflow.
    pending_call: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The real API/MCP response after an approved external-tool call
    # executes, or {"error": str} on failure - see
    # app.workflow.nodes.human_approval._execute_approved_external_call
    # and app.workflow.runner.resume_workflow. None until execution
    # actually happens (never set for a refund, which has no external call).
    execution_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # spec: Phase 15 - SLA targets computed once at creation (see
    # app.config.policies.SLA_FIRST_RESPONSE_MINUTES/SLA_RESOLUTION_MINUTES)
    # and the two real staff-action timestamps that satisfy them. Breach is
    # never stored - always computed on-demand from these vs. now().
    first_response_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    first_responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
