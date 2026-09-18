"""Tool permission matrix (spec §12).

Kept as data, not scattered `if` statements, so the policy is auditable and
configurable in one place. `app.security.authorization` enforces this.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApprovalLevel(StrEnum):
    NONE = "none"
    SOMETIMES = "sometimes"
    ALWAYS = "always"


@dataclass(frozen=True)
class ToolPolicy:
    ai_allowed: bool
    customer_confirmation: ApprovalLevel
    human_approval: ApprovalLevel


TOOL_PERMISSION_MATRIX: dict[str, ToolPolicy] = {
    "get_customer_profile": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_order": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_order_history": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_shipping_status": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_payment_status": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_subscription": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_refund_status": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "get_support_history": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "cancel_order": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.SOMETIMES),
    "create_refund_request": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.ALWAYS),
    "update_subscription": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.SOMETIMES),
    # spec: Phase 8.3 - a plain data update, not money-adjacent like a
    # refund - customer-confirmed but never held for human approval,
    # same tier as reset_password.
    "retry_payment": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.NONE),
    "reset_password": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.NONE),
    "create_support_ticket": ToolPolicy(True, ApprovalLevel.NONE, ApprovalLevel.NONE),
    "send_verification_email": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.NONE),
    "schedule_callback": ToolPolicy(True, ApprovalLevel.ALWAYS, ApprovalLevel.NONE),
    "security_investigation": ToolPolicy(False, ApprovalLevel.NONE, ApprovalLevel.ALWAYS),
    "account_deletion": ToolPolicy(False, ApprovalLevel.ALWAYS, ApprovalLevel.ALWAYS),
}

# Refund amounts at/above this threshold always require human approval,
# even though refunds already require it by default above.
HIGH_RISK_REFUND_AMOUNT_USD = 200.00


def get_tool_policy(tool_name: str) -> ToolPolicy:
    policy = TOOL_PERMISSION_MATRIX.get(tool_name)
    if policy is None:
        # Fail closed: unknown tools are never AI-allowed.
        return ToolPolicy(False, ApprovalLevel.ALWAYS, ApprovalLevel.ALWAYS)
    return policy


# spec §36 RBAC: security/fraud/legal tickets are a restricted queue -
# regular support staff cannot approve/reject them, only SECURITY_AGENT or
# ADMIN (spec §52: "Human/security queue", not the general agent queue).
SECURITY_QUEUE_INTENTS = {"SECURITY", "FRAUD", "LEGAL"}
SECURITY_QUEUE_ROLES = ("SECURITY_AGENT", "ADMIN")
GENERAL_QUEUE_ROLES = ("SUPPORT_AGENT", "SUPPORT_MANAGER", "ADMIN")


def roles_allowed_to_approve(ticket_intent: str) -> tuple[str, ...]:
    return SECURITY_QUEUE_ROLES if ticket_intent in SECURITY_QUEUE_INTENTS else GENERAL_QUEUE_ROLES


def ticket_queue_filter_for_role(role: str) -> tuple[str, set[str]] | None:
    """Scopes a ticket *queue listing* (`GET /support/tickets`) to what
    `role` may act on - the same split `roles_allowed_to_approve` enforces
    per-ticket, applied as a query filter instead. Returns `("include",
    intents)` / `("exclude", intents)`, or `None` for no filter (ADMIN
    sees every queue in one list)."""
    if role == "ADMIN":
        return None
    if role == "SECURITY_AGENT":
        return ("include", set(SECURITY_QUEUE_INTENTS))
    return ("exclude", set(SECURITY_QUEUE_INTENTS))  # SUPPORT_AGENT / SUPPORT_MANAGER
