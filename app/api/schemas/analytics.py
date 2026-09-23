"""spec: Phase 15 - Analytics. Every field here is a real aggregation over
existing tables (support_tickets/workflow_runs/feedback) - nothing is
estimated or fabricated. A metric this app genuinely cannot compute from
what it stores is simply not represented here rather than guessed."""

from __future__ import annotations

from pydantic import BaseModel


class TicketVolumePoint(BaseModel):
    date: str  # ISO date (day bucket)
    count: int


class IntentCount(BaseModel):
    intent: str
    count: int


class PriorityCount(BaseModel):
    priority: str
    count: int


class AgentActivity(BaseModel):
    staff_id: str
    approved_count: int
    rejected_count: int


class AnalyticsSummary(BaseModel):
    period_start: str
    period_end: str
    total_tickets: int
    resolved_tickets: int
    rejected_tickets: int
    open_tickets: int
    # None when no ticket in the period has both created_at and resolved_at
    # set - never fabricated as 0.
    avg_resolution_minutes: float | None
    median_resolution_minutes: float | None
    # spec: Phase 15 - computed on-demand (no scheduler exists in this
    # codebase - see app.config.policies' SLA constants), not stored.
    sla_breached_count: int
    sla_breach_rate: float | None
    total_workflow_runs: int
    escalated_workflow_runs: int
    escalation_rate: float | None
    csat_average: float | None
    csat_count: int
    ticket_volume_by_day: list[TicketVolumePoint]
    tickets_by_intent: list[IntentCount]
    tickets_by_priority: list[PriorityCount]
    agent_activity: list[AgentActivity]
