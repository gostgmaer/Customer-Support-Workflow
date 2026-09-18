"""policy_check node (spec §16, §30)."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.reviewer import check_policy
from app.observability.logging import get_logger
from app.workflow.deps import get_deps
from app.workflow.state import SupportState

logger = get_logger(__name__)


async def policy_check(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    llm = deps.llm_router.get_model("policy_check")
    result = await check_policy(
        llm,
        response=(state.get("draft_response") or ""),
        intent=(state.get("intent") or "UNKNOWN"),
        tool_results=state.get("tool_results", []),
    )
    if not result.approved:
        logger.warning("policy_check_rejected", violations=result.violations, severity=result.severity)
    update: dict = {"policy_violations": result.violations}
    if result.requires_human:
        update["requires_human"] = True
    return update
