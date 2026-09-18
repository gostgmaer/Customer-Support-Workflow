from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TicketResponse(BaseModel):
    id: str
    conversation_id: str
    customer_id: str
    workflow_run_id: str | None
    intent: str
    priority: str
    status: str
    summary: str
    customer_problem: str
    actions_taken: list[str]
    tools_used: list[str]
    relevant_documents: list[str]
    reason_for_escalation: str
    recommended_next_action: str
    approved_by: str | None
    external_ref: str | None
    external_url: str | None
    # spec: Phase 8.2 - the proposed external-tool call (None for a
    # refund ticket) and its real result once approved and executed.
    pending_call: dict[str, Any] | None
    execution_result: dict[str, Any] | None
    created_at: datetime


class ApproveTicketRequest(BaseModel):
    workflow_run_id: str
    # spec: Phase 8.2 - staff-edited overrides for an external-tool
    # ticket's proposed arguments, merged into the AI-proposed ones
    # (only the changed keys need to be sent). Ignored for a refund
    # ticket, which has no pending_mcp_call to merge into.
    arguments: dict[str, Any] | None = None


class RejectTicketRequest(BaseModel):
    workflow_run_id: str
    reason: str = ""
