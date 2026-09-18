"""Authorization (spec §10-12): tool permission matrix + ownership checks.

Tools call `authorize_tool_call` before touching any data; it fails closed
for unknown tools and raises AuthorizationError on any ownership mismatch,
which is the only path by which a customer's own token can access data -
there is no path for cross-customer access.
"""

from __future__ import annotations

from app.config.policies import ApprovalLevel, ToolPolicy, get_tool_policy
from app.domain.exceptions import AuthorizationError


def authorize_tool_call(
    *, tool_name: str, requesting_customer_id: str, target_customer_id: str
) -> ToolPolicy:
    if requesting_customer_id != target_customer_id:
        raise AuthorizationError(
            f"Customer {requesting_customer_id} is not authorized to act on "
            f"customer {target_customer_id}'s data",
            details={"tool_name": tool_name},
        )
    policy = get_tool_policy(tool_name)
    if not policy.ai_allowed:
        raise AuthorizationError(
            f"Tool '{tool_name}' may not be invoked by the AI agent", details={"tool_name": tool_name}
        )
    return policy


def requires_human_approval(policy: ToolPolicy, *, escalation_forced: bool = False) -> bool:
    if escalation_forced:
        return True
    return policy.human_approval == ApprovalLevel.ALWAYS or (
        policy.human_approval == ApprovalLevel.SOMETIMES
    )


def requires_customer_confirmation(policy: ToolPolicy) -> bool:
    return policy.customer_confirmation != ApprovalLevel.NONE
