"""send_response node (spec §30). Persists the assistant message and sets
`final_response`. If the response loop was forcibly stopped without ever
becoming acceptable, substitutes a safe fallback and forces escalation
(rule 13: never silently fail)."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.observability.metrics import ESCALATIONS
from app.repositories.conversations import ConversationRepository
from app.workflow.deps import get_deps
from app.workflow.routers.review_router import is_response_acceptable
from app.workflow.state import SupportState

FALLBACK_RESPONSE = (
    "I want to make sure I give you accurate information, and I'm not confident "
    "I can do that for this request right now. I'm escalating this to a member "
    "of our support team who will follow up with you shortly."
)


async def send_response(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    update: dict = {}

    if is_response_acceptable(state):
        final_response = state.get("draft_response") or FALLBACK_RESPONSE
    else:
        final_response = FALLBACK_RESPONSE
        update["requires_human"] = True
        update["escalation_reason"] = state.get("escalation_reason") or "repeated failed resolution"
        ESCALATIONS.labels(reason="repeated_failed_resolution").inc()

    repo = ConversationRepository(deps.session, state["tenant_id"])
    await repo.add_message(
        conversation_id=state["conversation_id"], role="assistant", content=final_response
    )

    update["final_response"] = final_response
    return update
