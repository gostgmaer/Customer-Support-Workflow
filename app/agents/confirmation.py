"""Shared "is this message confirming a pending action?" detection.

A short reply like "yes" or "go ahead" carries none of the original
intent's keywords, so classifying it independently (see
app.agents.classifier) would misroute it as UNKNOWN. Both the intent
classifier (to keep routing to the same resolver) and the resolution agent
(to decide whether to actually call a mutating tool) need this same
detection, so it lives in one place.
"""

from __future__ import annotations

import re

_CONFIRM_ASK_RE = re.compile(r"\bconfirm\b", re.I)
_CONFIRM_YES_RE = re.compile(r"\b(yes|confirm|go ahead|please do|proceed|sounds good)\b", re.I)
_CONFIRM_NO_RE = re.compile(r"\b(no|don'?t|cancel that|never mind|nevermind|stop)\b", re.I)

# Intents whose resolver can leave a conversation "awaiting confirmation" -
# see app.agents.resolution's resolve_order_cancel/resolve_refund/resolve_subscription.
# EXCHANGE deliberately excluded - it has no internal resolver, so no
# confirmation round-trip to keep track of (see COMMERCE_INTENTS's comment
# in app.agents.resolution).
CONFIRMATION_CAPABLE_INTENTS = {
    "ORDER_CANCEL", "REFUND", "RETURNS", "SUBSCRIPTION",
    "SUBSCRIPTION_CHANGE", "ADDRESS_CHANGE", "PAYMENT_RETRY",
    # spec: Phase 13 - PROFILE_UPDATE/ACCOUNT_ACCESS (account unlock) both
    # gained a pending_confirmation step (resolve_profile_update/
    # resolve_account_access); BILLING's duplicate-charge sub-case
    # (_resolve_duplicate_charge) also does.
    "PROFILE_UPDATE", "ACCOUNT_ACCESS", "BILLING",
}


def last_assistant_asked_to_confirm(history: list[dict]) -> bool:
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            return bool(_CONFIRM_ASK_RE.search(msg.get("content", "")))
    return False


def interpret_confirmation_reply(message: str) -> bool | None:
    """Returns True (affirmed), False (declined), or None (not a plain
    yes/no-style reply at all - e.g. the customer asked something else)."""
    if _CONFIRM_NO_RE.search(message):
        return False
    if _CONFIRM_YES_RE.search(message):
        return True
    return None


def customer_already_confirmed(history: list[dict], message: str) -> bool:
    if not last_assistant_asked_to_confirm(history):
        return False
    return interpret_confirmation_reply(message) is True
