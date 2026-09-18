"""regenerate node (spec §15-16, §30): re-drafts the response incorporating
the reasons it was rejected, then loops back to policy_check.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.resolution import draft_response
from app.security.pii import redact
from app.workflow.deps import get_deps
from app.workflow.state import SupportState


async def regenerate(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    issues = [*state.get("policy_violations", []), *state.get("review_issues", [])]
    if not state.get("grounded", True):
        issues.append("response contained claims not supported by verified facts")

    facts = [
        *state.get("resolution_facts", []),
        f"Previous draft was rejected for: {'; '.join(issues) or 'unspecified reasons'}. "
        "Address this without inventing new facts.",
    ]
    llm = deps.llm_router.get_model("resolution_response")
    response = await draft_response(llm, message=redact(state["latest_message"]), facts=facts)
    return {
        "draft_response": response,
        "regenerate_count": state.get("regenerate_count", 0) + 1,
    }
