"""Post-response-review conditional edge (spec §30): approved -> send_response,
rejected -> regenerate (bounded, then forced escalation).
"""

from __future__ import annotations

from typing import Literal

from app.config import get_settings
from app.workflow.state import SupportState

Decision = Literal["approved", "rejected"]


def is_response_acceptable(state: SupportState) -> bool:
    return (
        not state.get("policy_violations")
        and state.get("grounded", True)
        and not state.get("review_issues")
    )


def route_after_review(state: SupportState) -> Decision:
    if is_response_acceptable(state):
        return "approved"

    settings = get_settings()
    max_attempts = state.get("runtime_config", {}).get(
        "escalation_max_failed_attempts", settings.escalation_max_failed_attempts
    )
    if state.get("regenerate_count", 0) >= max_attempts:
        return "approved"  # stop looping; send_response will detect requires_human and use a safe fallback
    return "rejected"
