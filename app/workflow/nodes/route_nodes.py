"""knowledge_search / customer_data / action_required / human_escalation nodes
(spec §30). Each tags `state["route"]`; knowledge_search additionally
performs retrieval since that is a read-only, side-effect-free lookup with
no dependency on which mutating/read-only tool resolve_issue will later
call. human_escalation sets the escalation flags immediately so downstream
nodes (and the API response) see requires_human=True even if later steps
fail.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.observability.logging import get_logger
from app.observability.metrics import ESCALATIONS
from app.security.pii import redact
from app.workflow.deps import get_deps
from app.workflow.state import SupportState

logger = get_logger(__name__)


async def knowledge_search_node(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    docs = await deps.retriever.retrieve(
        redact(state["latest_message"]),
        tenant_id=state["tenant_id"],
        min_score=state.get("runtime_config", {}).get("confidence_retrieval"),
    )
    return {
        "route": "knowledge_search",
        "retrieved_documents": [
            {
                "document_id": d.document_id,
                "title": d.title,
                "source": d.source,
                "category": d.category,
                "text": d.text,
                "score": d.score,
            }
            for d in docs
        ],
    }


async def customer_data_node(state: SupportState, config: RunnableConfig) -> dict:
    return {"route": "customer_data"}


async def action_required_node(state: SupportState, config: RunnableConfig) -> dict:
    return {"route": "action_required"}


async def human_escalation_node(state: SupportState, config: RunnableConfig) -> dict:
    intent = (state.get("intent") or "UNKNOWN")
    reason = {
        "SECURITY": "Security-sensitive request - always escalated to a human specialist.",
        "FRAUD": "Suspected fraud - always escalated to a human specialist.",
        "LEGAL": "Legal matter - always escalated to a human specialist.",
    }.get(intent, "Low classification confidence or explicit escalation trigger.")
    ESCALATIONS.labels(reason=intent).inc()
    logger.info("workflow_escalation_triggered", intent=intent, reason=reason)
    return {"route": "human_escalation", "requires_human": True, "escalation_reason": reason}
