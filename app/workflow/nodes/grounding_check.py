"""grounding_check node (spec §15, §30).

Skipped (auto-pass) once the workflow has already decided to escalate to a
human: at that point the response only acknowledges the escalation, which
is a true statement about system state, not a factual claim requiring
evidence.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.reviewer import check_grounding
from app.workflow.deps import get_deps
from app.workflow.state import SupportState


async def grounding_check(state: SupportState, config: RunnableConfig) -> dict:
    if state.get("requires_human"):
        return {"grounded": True, "response_confidence": 1.0}

    deps = get_deps(config)
    llm = deps.llm_router.get_model("grounding_check")
    result = await check_grounding(
        llm, response=(state.get("draft_response") or ""), facts=state.get("resolution_facts", [])
    )
    return {"grounded": result.grounded, "response_confidence": result.confidence}
