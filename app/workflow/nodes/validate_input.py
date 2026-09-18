"""validate_input node (spec §3.1, §30)."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.domain.exceptions import ValidationError
from app.security.prompt_security import detect_injection_attempt
from app.workflow.state import SupportState

REQUIRED_FIELDS = ("conversation_id", "customer_id", "message_id", "latest_message")


async def validate_input(state: SupportState, config: RunnableConfig) -> dict:
    missing = [f for f in REQUIRED_FIELDS if not state.get(f)]
    if missing:
        raise ValidationError(f"Missing required fields: {missing}")

    safety_flags = list(state.get("safety_flags", []))
    if detect_injection_attempt(state["latest_message"]):
        safety_flags.append("possible_prompt_injection")

    return {
        "safety_flags": safety_flags,
        "errors": [],
        "retry_count": 0,
        "tool_calls": [],
        "tool_results": [],
    }
