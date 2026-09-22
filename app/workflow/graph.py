"""LangGraph workflow assembly (spec §30).

    START -> validate_input -> load_conversation -> classify_intent ->
    classify_priority -> detect_sentiment -> route_request
        -> {knowledge_search|customer_data|action_required|human_escalation}
        -> resolve_issue -> policy_check -> grounding_check ->
           response_review
        -> {approved -> send_response, rejected -> regenerate -> policy_check}
    send_response -> save_outcome -> END

Human approval (§18) is implemented with LangGraph's `interrupt()` inside
the `human_approval_gate` node, backed by a checkpointer so the pause
survives process restarts - see app.workflow.nodes.human_approval.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.dynamic_settings import get_effective_settings
from app.domain.exceptions import SupportWorkflowError
from app.domain.models import WorkflowEvent
from app.llm.base import TokenUsage
from app.llm.router import RecordingLLMRouter
from app.observability.logging import get_logger
from app.repositories.cost import ModelRequestRepository
from app.workflow.deps import WorkflowDeps, get_deps
from app.workflow.nodes.classify import (
    classify_intent_node,
    classify_priority_node,
    detect_sentiment_node,
)
from app.workflow.nodes.grounding_check import grounding_check
from app.workflow.nodes.human_approval import human_approval_gate
from app.workflow.nodes.load_conversation import load_conversation
from app.workflow.nodes.policy_check import policy_check
from app.workflow.nodes.regenerate import regenerate
from app.workflow.nodes.resolve_issue import resolve_issue
from app.workflow.nodes.response_review import response_review
from app.workflow.nodes.route_nodes import (
    action_required_node,
    customer_data_node,
    human_escalation_node,
    knowledge_search_node,
)
from app.workflow.nodes.save_outcome import save_outcome
from app.workflow.nodes.send_response import send_response
from app.workflow.nodes.validate_input import validate_input
from app.workflow.routers.review_router import route_after_review
from app.workflow.routers.route_request import route_request
from app.workflow.state import SupportState

logger = get_logger(__name__)

Node = Callable[[SupportState, RunnableConfig], Awaitable[dict]]

# Nodes that call an LLM (directly or via app.agents.*) - see
# app.llm.base.LLMProvider. Every other node is deterministic Python and
# never touches deps.llm_router, so cost tracking/budget checks only need
# to wrap these.
# Which keys of a node's returned state-update dict are worth persisting
# onto its WorkflowEvent row (spec §22/§27's "make every important
# workflow decision observable") - a curated, decision-relevant subset,
# not the full dict: `tool_results`/`execution_result`/full response text
# either duplicate what `tool_executions`/`support_tickets` already store
# durably, or carry customer-message-length text that doesn't belong
# replicated onto every node's trace row. This is what actually turns
# `workflow_events` from a timing-only table into a real "what did the
# agent decide, at each step" audit trail - previously defined
# (`WorkflowEvent.data`) but never once populated.
_TRACKED_EVENT_KEYS = (
    "intent",
    "intent_confidence",
    "priority",
    "sentiment",
    "route",
    "tool_calls",
    "requires_human",
    "escalation_reason",
    "awaiting_approval",
    "grounded",
    "response_confidence",
    "policy_violations",
    "review_issues",
    "regenerate_count",
)


def _event_data(result: dict) -> dict:
    return {key: result[key] for key in _TRACKED_EVENT_KEYS if key in result}


LLM_CALLING_NODES = {
    "classify_intent",
    "classify_priority",
    "detect_sentiment",
    "resolve_issue",
    "policy_check",
    "grounding_check",
    "response_review",
    "regenerate",
}


async def _budget_exceeded(
    state: SupportState, cost_repo: ModelRequestRepository, session: AsyncSession
) -> bool:
    effective = await get_effective_settings(session, state["tenant_id"])
    if effective.llm_budget_usd_per_run is None:
        return False
    spent = await cost_repo.total_cost_for_run(state.get("workflow_run_id", ""))
    return spent >= effective.llm_budget_usd_per_run


def _traced(node_name: str, fn: Node) -> Node:
    """Wraps a node so every execution is recorded in `workflow_events`
    (spec §22/§27: "make every important workflow decision observable"),
    and - for LLM-calling nodes - every model call is recorded in
    `model_requests` (spec §42) and a configured per-run budget is
    enforced, all without every node module needing its own boilerplate.

    Events are committed immediately (not just flushed) so the trail
    survives even when a later node in the same run fails.
    """

    async def wrapper(state: SupportState, config: RunnableConfig) -> dict:
        deps = get_deps(config)
        start = time.perf_counter()

        if node_name in LLM_CALLING_NODES:
            cost_repo = ModelRequestRepository(deps.session, state["tenant_id"])
            if await _budget_exceeded(state, cost_repo, deps.session):
                logger.warning(
                    "llm_budget_exceeded", node_name=node_name, workflow_run_id=state.get("workflow_run_id")
                )
                deps.session.add(
                    WorkflowEvent(
                        workflow_run_id=state.get("workflow_run_id", ""),
                        node_name=node_name,
                        status="budget_exceeded",
                        duration_ms=(time.perf_counter() - start) * 1000,
                    )
                )
                await deps.session.commit()
                return {
                    "requires_human": True,
                    "escalation_reason": "LLM budget exceeded for this request",
                }

            async def _on_usage(usage: TokenUsage) -> None:
                await cost_repo.record(
                    workflow_run_id=state.get("workflow_run_id"),
                    node_name=node_name,
                    purpose=node_name,
                    provider=usage.provider,
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    estimated_cost_usd=usage.estimated_cost_usd,
                )
                await deps.session.commit()

            original_router = deps.llm_router
            deps.llm_router = RecordingLLMRouter(original_router, _on_usage)  # type: ignore[assignment]
            try:
                result = await _run_and_log(fn, state, config, deps, node_name, start)
            finally:
                deps.llm_router = original_router
            return result

        return await _run_and_log(fn, state, config, deps, node_name, start)

    return wrapper


async def _run_and_log(
    fn: Node, state: SupportState, config: RunnableConfig, deps: WorkflowDeps, node_name: str, start: float
) -> dict:
    try:
        result = await fn(state, config)
    except GraphInterrupt:
        deps.session.add(
            WorkflowEvent(
                workflow_run_id=state.get("workflow_run_id", ""),
                node_name=node_name,
                status="interrupted",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        )
        await deps.session.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        code = exc.code if isinstance(exc, SupportWorkflowError) else "UNKNOWN_ERROR"
        deps.session.add(
            WorkflowEvent(
                workflow_run_id=state.get("workflow_run_id", ""),
                node_name=node_name,
                status="failed",
                duration_ms=(time.perf_counter() - start) * 1000,
                error_code=code,
            )
        )
        await deps.session.commit()
        raise
    else:
        deps.session.add(
            WorkflowEvent(
                workflow_run_id=state.get("workflow_run_id", ""),
                node_name=node_name,
                status="succeeded",
                duration_ms=(time.perf_counter() - start) * 1000,
                data=_event_data(result),
            )
        )
        await deps.session.commit()
        return result


NODES: dict[str, Node] = {
    "validate_input": validate_input,
    "load_conversation": load_conversation,
    "classify_intent": classify_intent_node,
    "classify_priority": classify_priority_node,
    "detect_sentiment": detect_sentiment_node,
    "knowledge_search": knowledge_search_node,
    "customer_data": customer_data_node,
    "action_required": action_required_node,
    "human_escalation": human_escalation_node,
    "resolve_issue": resolve_issue,
    "human_approval_gate": human_approval_gate,
    "policy_check": policy_check,
    "grounding_check": grounding_check,
    "response_review": response_review,
    "regenerate": regenerate,
    "send_response": send_response,
    "save_outcome": save_outcome,
}


def build_graph() -> StateGraph:
    graph = StateGraph(SupportState)

    for name, fn in NODES.items():
        graph.add_node(name, _traced(name, fn))  # type: ignore[call-overload]

    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "load_conversation")
    graph.add_edge("load_conversation", "classify_intent")
    graph.add_edge("classify_intent", "classify_priority")
    graph.add_edge("classify_priority", "detect_sentiment")

    graph.add_conditional_edges(
        "detect_sentiment",
        route_request,
        {
            "knowledge_search": "knowledge_search",
            "customer_data": "customer_data",
            "action_required": "action_required",
            "human_escalation": "human_escalation",
        },
    )

    for branch in ("knowledge_search", "customer_data", "action_required", "human_escalation"):
        graph.add_edge(branch, "resolve_issue")

    graph.add_edge("resolve_issue", "human_approval_gate")
    graph.add_edge("human_approval_gate", "policy_check")

    graph.add_edge("policy_check", "grounding_check")
    graph.add_edge("grounding_check", "response_review")
    graph.add_conditional_edges(
        "response_review",
        route_after_review,
        {"approved": "send_response", "rejected": "regenerate"},
    )
    graph.add_edge("regenerate", "policy_check")

    graph.add_edge("send_response", "save_outcome")
    graph.add_edge("save_outcome", END)

    return graph
