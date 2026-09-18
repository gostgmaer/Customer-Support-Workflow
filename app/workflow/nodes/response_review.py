"""response_review node (spec §14, §30): a final tone/quality/clarity gate,
separate from policy (§16) and grounding (§15).
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.schemas import ResponseReview
from app.llm.base import LLMProvider
from app.security.prompt_security import build_prompt_messages
from app.workflow.deps import get_deps
from app.workflow.state import SupportState

_REVIEW_RULES = (
    "Review the RESPONSE for clarity, professionalism, and empathy. If it is "
    "acceptable, set approved=true. If it has fixable tone/clarity issues, "
    "set approved=false and provide a corrected `revised_response`. Do not "
    "change any factual content, only tone/clarity."
)


async def _review(llm: LLMProvider, response: str) -> ResponseReview:
    messages = build_prompt_messages(
        business_policies="", developer_rules=f"{_REVIEW_RULES}\n\nRESPONSE:\n{response}",
        retrieved_knowledge=[], customer_message=response,
    )
    return await llm.generate_structured(messages, schema=ResponseReview)


async def response_review(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    llm = deps.llm_router.get_model("response_review")
    result = await _review(llm, (state.get("draft_response") or ""))
    update: dict = {"review_issues": result.issues}
    if not result.approved and result.revised_response:
        update["draft_response"] = result.revised_response
        update["review_issues"] = []
    elif not result.approved:
        update["review_issues"] = result.issues or ["response_review_rejected"]
    return update
