"""resolve_issue node (spec §13, §30)."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.resolution import draft_response, extract_profile_update_target, gather_resolution_facts
from app.rag.retriever import RetrievedDocument
from app.security.pii import redact
from app.tools.base import ToolContext
from app.workflow.deps import get_deps
from app.workflow.state import SupportState

_SENSITIVE_INTENTS = {"SECURITY", "FRAUD", "LEGAL"}


async def resolve_issue(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    llm = deps.llm_router.get_model("resolution_response")
    intent = (state.get("intent") or "UNKNOWN")
    raw_message = state["latest_message"]
    message = redact(raw_message)
    # spec: Phase 13 - a new target email is exactly the kind of thing
    # redact() strips before any resolver sees it (see
    # app.agents.resolution.extract_profile_update_target's docstring) -
    # extracted from the RAW message here, at the one point it's still
    # available, and never passed further as the raw message itself.
    profile_update_target = extract_profile_update_target(raw_message) if intent == "PROFILE_UPDATE" else None

    if intent in _SENSITIVE_INTENTS:
        # Never call customer-data tools for these - the human agent
        # investigates directly. The acknowledgment response makes no
        # factual claims beyond "this has been escalated".
        facts = ["This request has been escalated to a human specialist for review."]
        response = await draft_response(llm, message=message, facts=facts)
        return {
            "draft_response": response,
            "tool_calls": [],
            "tool_results": [],
            "resolution_facts": facts,
            "awaiting_approval": False,
        }

    retrieved_documents = [
        RetrievedDocument(
            document_id=d["document_id"], chunk_id="", title=d["title"], source=d["source"],
            category=d["category"], text=d["text"], score=d["score"],
        )
        for d in state.get("retrieved_documents", [])
    ]

    ctx = ToolContext(
        session=deps.session,
        requesting_customer_id=state["customer_id"],
        workflow_run_id=state.get("workflow_run_id", ""),
        tenant_id=state["tenant_id"],
    )
    outcome = await gather_resolution_facts(
        ctx,
        intent=intent,
        customer_id=state["customer_id"],
        conversation_id=state["conversation_id"],
        message_id=state["message_id"],
        message=message,
        history=state.get("messages", []),
        retrieved_documents=retrieved_documents,
        llm=llm,
        retriever=deps.retriever,
        profile_update_target=profile_update_target,
    )

    response = await draft_response(llm, message=message, facts=outcome.facts)

    update: dict = {
        "draft_response": response,
        "tool_calls": outcome.tool_calls,
        "tool_results": outcome.tool_results,
        "errors": outcome.errors,
        "resolution_facts": outcome.facts,
    }
    if outcome.requires_human:
        update["requires_human"] = True
    if outcome.escalation_reason and not state.get("escalation_reason"):
        update["escalation_reason"] = outcome.escalation_reason
        update["requires_human"] = True
    update["awaiting_approval"] = outcome.awaiting_approval
    update["pending_mcp_call"] = outcome.pending_mcp_call
    update["pending_internal_call"] = outcome.pending_internal_call
    return update
