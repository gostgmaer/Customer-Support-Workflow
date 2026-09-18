"""Intent (§5), priority (§6), and sentiment (§7) classification.

Sentiment is never the sole basis for approving/denying a request - it only
feeds tone/priority/escalation signals (enforced by keeping it a separate,
narrowly-scoped call whose output only ever nudges `priority`, never gates
policy_check/grounding_check).
"""

from __future__ import annotations

from app.agents.schemas import IntentClassification, PriorityClassification, SentimentDetection
from app.domain.enums.intent import ALWAYS_ESCALATE_INTENTS, Intent
from app.domain.enums.priority import Priority
from app.domain.enums.sentiment import ESCALATION_SIGNAL_SENTIMENTS, Sentiment
from app.domain.exceptions import LLMError
from app.llm.base import LLMProvider
from app.observability.logging import get_logger
from app.security.prompt_security import build_prompt_messages

logger = get_logger(__name__)

# spec: Phase 9.2 - built from the real Intent enum rather than a vague
# "from the allowed list" (the root cause of a real, previously
# unfixed bug: three separate live-testing incidents, all involving an
# order-id-shaped token in the message misclassifying as UNKNOWN, were
# each logged as "a live-testing finding" and cross-referenced as "the
# same variance" but never traced to the actual cause - this prompt
# never once named any of the 24 real intent values anywhere in its
# text). Listing them here can never silently drift out of sync with
# `Intent` again the way it did across Phase 8.3 adding four new
# members that this prompt never mentioned.
_INTENT_SYSTEM_RULES = (
    "Classify the customer's message into exactly one intent from this exact "
    "list: " + ", ".join(i.value for i in Intent) + ". Do not expose this "
    "reasoning to the customer - `reasoning_summary` is for internal "
    "operational logs only."
)

_INTENT_RETRY_SUFFIX = (
    "\n\nYour previous answer was not one of the allowed intents listed above. "
    "Choose the single closest match from that exact list, or UNKNOWN only if "
    "truly none of them apply."
)

_PRIORITY_SYSTEM_RULES = (
    "Classify ticket priority as LOW, MEDIUM, HIGH, or CRITICAL considering "
    "security/fraud risk, payment problems, account lockout, business impact, "
    "customer sentiment, and SLA requirements."
)

_SENTIMENT_SYSTEM_RULES = (
    "Detect the customer's sentiment. This is used only for tone adaptation "
    "and escalation signaling - never to approve or deny a request on its own."
)


def _unknown_fallback(reason: str) -> IntentClassification:
    return IntentClassification(
        intent=Intent.UNKNOWN.value,
        confidence=0.0,
        reasoning_summary=reason,
        requires_customer_data=False,
        requires_tool=False,
        requires_human=False,
    )


async def _classify_intent_once(
    llm: LLMProvider, message: str, *, retry: bool
) -> IntentClassification | None:
    """Returns None on a schema-validation failure (IntentClassification.intent
    is now a real Literal enum - see app.agents.schemas - so a provider that
    doesn't strictly enforce it could still return an out-of-taxonomy string,
    which LangChain's with_structured_output surfaces as an LLMError rather
    than an invalid IntentClassification instance). Never raises - the
    caller decides whether to retry or fall back to UNKNOWN, matching this
    codebase's "escalate rather than guess" posture for every other
    classification failure mode."""
    rules = _INTENT_SYSTEM_RULES + (_INTENT_RETRY_SUFFIX if retry else "")
    messages = build_prompt_messages(
        business_policies="", developer_rules=rules, retrieved_knowledge=[], customer_message=message,
    )
    try:
        return await llm.generate_structured(messages, schema=IntentClassification)
    except LLMError as exc:
        logger.warning("intent_classification_schema_mismatch", retry=retry, error=str(exc))
        return None


async def classify_intent(llm: LLMProvider, message: str) -> IntentClassification:
    result = await _classify_intent_once(llm, message, retry=False)
    if result is None or result.intent == Intent.UNKNOWN.value:
        # One bounded retry, specifically targeting the "model landed on
        # UNKNOWN (or failed to match the taxonomy at all) the first time"
        # failure mode - not a generic retry-everything loop, so the
        # common (correct-on-first-try) case costs exactly one call, same
        # as before this fix.
        retried = await _classify_intent_once(llm, message, retry=True)
        if retried is not None:
            result = retried
    if result is None:
        result = _unknown_fallback("Intent classification failed schema validation twice")
    if result.intent in {i.value for i in ALWAYS_ESCALATE_INTENTS}:
        result.requires_human = True
    return result


async def classify_priority(llm: LLMProvider, message: str, *, intent: str) -> PriorityClassification:
    messages = build_prompt_messages(
        business_policies="", developer_rules=f"{_PRIORITY_SYSTEM_RULES}\nClassified intent: {intent}",
        retrieved_knowledge=[], customer_message=message,
    )
    result = await llm.generate_structured(messages, schema=PriorityClassification)
    if result.priority not in {p.value for p in Priority}:
        result.priority = Priority.MEDIUM.value
    if intent in {i.value for i in ALWAYS_ESCALATE_INTENTS}:
        result.priority = Priority.CRITICAL.value
    return result


async def detect_sentiment(llm: LLMProvider, message: str) -> SentimentDetection:
    messages = build_prompt_messages(
        business_policies="", developer_rules=_SENTIMENT_SYSTEM_RULES,
        retrieved_knowledge=[], customer_message=message,
    )
    result = await llm.generate_structured(messages, schema=SentimentDetection)
    if result.sentiment not in {s.value for s in Sentiment}:
        result.sentiment = Sentiment.NEUTRAL.value
    return result


def sentiment_escalates_priority(sentiment: str) -> bool:
    return sentiment in {s.value for s in ESCALATION_SIGNAL_SENTIMENTS}
