"""LangGraph workflow state (spec §4).

Deliberately keeps only what nodes need to route/decide. Sensitive customer
data fetched via tools is summarized before being placed in `customer_context`
(see app.security.pii) rather than stored raw.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class SupportState(TypedDict, total=False):
    conversation_id: str
    customer_id: str
    message_id: str
    # spec §43: every entity a run touches must stay within this tenant.
    tenant_id: str

    # Overwritten (not accumulated) each run with the full DB-sourced history,
    # since app.repositories.conversations.Message is the durable source of
    # truth - accumulating here would duplicate entries across turns.
    messages: list[dict]
    latest_message: str

    intent: str | None
    intent_confidence: float | None
    # The conversation's intent as of the *previous* turn (from the
    # persisted Conversation row) - lets classify_intent_node recognize a
    # short confirmation reply ("yes", "go ahead") as continuing the same
    # intent instead of misclassifying it as UNKNOWN.
    previous_intent: str | None

    priority: str | None
    sentiment: str | None

    customer_context: dict[str, Any]
    retrieved_documents: list[dict]

    tool_calls: Annotated[list[dict], operator.add]
    tool_results: Annotated[list[dict], operator.add]

    draft_response: str | None
    response_confidence: float | None

    requires_human: bool
    escalation_reason: str | None

    policy_violations: list[str]
    safety_flags: list[str]
    resolution_facts: list[str]
    grounded: bool
    review_issues: list[str]

    retry_count: int
    errors: Annotated[list[dict], operator.add]

    final_response: str | None

    # Internal bookkeeping not in the spec's minimum list but required to
    # route/persist correctly:
    workflow_run_id: str
    channel: str
    route: str | None
    regenerate_count: int
    awaiting_approval: bool
    approved: bool | None
    # Set by resolve_issue (via app.agents.external_tools's fallback) when
    # awaiting_approval is for a proposed external (MCP or OpenAPI) tool
    # call rather than a refund - human_approval_gate reads this to know
    # what to actually call once approved. None for every other
    # awaiting_approval case. Field name kept as `pending_mcp_call` (not
    # renamed when OpenAPI support was added) for checkpoint
    # backward-compatibility with any run already interrupted at deploy
    # time - its dict contents carry a `source` key instead.
    pending_mcp_call: dict[str, Any] | None
    # spec: Phase 13 - analogous to pending_mcp_call but for an internal,
    # reviewed-code tool that still must not run until a human approves it
    # (update_customer_profile, unlock_account - identity-modifying, always
    # human-approved per app.config.policies). {"tool": str, "args": dict}.
    # None for every other awaiting_approval case.
    pending_internal_call: dict[str, Any] | None
    # spec: Phase 8.2 - the raw result (or {"error": str} on failure) of
    # an approved external-tool call, set by
    # app.workflow.nodes.human_approval._execute_approved_external_call
    # so app.workflow.runner.resume_workflow can persist it onto the
    # ticket. A plain single value, not accumulated across nodes - unset
    # for every path that isn't an external-tool approval.
    execution_result: dict[str, Any] | None

    # Resolved once at run start (app.config.dynamic_settings.get_effective_settings)
    # and carried in state rather than deps, since routing functions
    # (app.workflow.routers.*) only receive state, not the RunnableConfig
    # deps live on. Plain JSON-safe scalars, so this stays checkpoint-safe.
    # Absent (e.g. state built directly in a test) -> callers fall back to
    # app.config.get_settings()'s env-var default.
    runtime_config: dict[str, float | int]
