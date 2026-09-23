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
    # spec: Phase 15 - SLA targets/timestamps. Breach is never stored -
    # compute it client-side (or in an analytics query) from these vs. now().
    first_response_due_at: datetime | None
    resolution_due_at: datetime | None
    first_responded_at: datetime | None
    resolved_at: datetime | None


class WorkflowEventResponse(BaseModel):
    """One node's execution within the run that produced this ticket -
    spec: 'log what the agent actually does, so every action is
    traceable' (see app.workflow.graph._traced, which now populates
    `data` with the decision-relevant fields each node returned -
    previously defined but always empty)."""

    node_name: str
    status: str
    duration_ms: float | None
    error_code: str | None
    data: dict[str, Any]
    created_at: datetime


class ToolExecutionResponse(BaseModel):
    """One real tool call (internal or external/MCP/OpenAPI) made during
    the run - arguments/result are PII-redacted before storage (see
    app.tools.base.run_tool / record_external_tool_execution)."""

    tool_name: str
    arguments: dict[str, Any]
    result_summary: dict[str, Any]
    success: bool
    duration_ms: float | None
    created_at: datetime


class TicketTraceResponse(BaseModel):
    workflow_run_id: str
    events: list[WorkflowEventResponse]
    tool_executions: list[ToolExecutionResponse]


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
