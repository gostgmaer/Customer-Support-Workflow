"""Deterministic mock LLM provider.

Used automatically when MOCK_LLM=true (the zero-setup default) and in
tests, so behavior is reproducible without any API key. It does simple
keyword matching against the latest user message rather than anything
resembling reasoning - it exists to make the *workflow* (routing, tool
calls, policy/grounding gates, escalation) exercisable end-to-end offline,
not to demonstrate NLU quality. Swap MOCK_LLM=false for real
understanding.
"""

from __future__ import annotations

import inspect
import re
from typing import TypeVar

from pydantic import BaseModel

from app.llm.base import LLMMessage, TokenUsage, UsageCallback

T = TypeVar("T", bound=BaseModel)

_KEYWORD_INTENTS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\b(hack|unauthorized|didn'?t (log|sign) in|login notification|someone accessed)\b", re.I
        ),
        "SECURITY",
    ),
    (re.compile(r"\bfraud(ulent)?\b", re.I), "FRAUD"),
    (re.compile(r"\b(refund|money back|damaged)\b", re.I), "REFUND"),
    (re.compile(r"\bcancel\b.*\border\b|\border\b.*\bcancel\b", re.I), "ORDER_CANCEL"),
    (
        re.compile(
            r"\bwhere.*(order|package)|track.*(order|package)|order status\b|"
            r"(check|status).*\border\b|\border\b.*(check|status)",
            re.I,
        ),
        "ORDER_STATUS",
    ),
    (re.compile(r"\bpassword\b", re.I), "PASSWORD_RESET"),
    # Specific-before-general (spec: Phase 8.3): an "upgrade/downgrade my
    # plan" message must match SUBSCRIPTION_CHANGE, not the broader
    # SUBSCRIPTION pattern below it.
    (
        re.compile(r"\b(upgrade|downgrade)\b.*\b(plan|subscription)\b|\bchange\b.*\bplan\b", re.I),
        "SUBSCRIPTION_CHANGE",
    ),
    (re.compile(r"\bcancel\b.*\bsubscription\b|\bsubscription\b", re.I), "SUBSCRIPTION"),
    (re.compile(r"\bretry\b.*\bpayment\b|\bpayment\b.*\bretry\b", re.I), "PAYMENT_RETRY"),
    (re.compile(r"\bpayment (failed|declined)\b|charged.*fail|money.*deduct", re.I), "PAYMENT_FAILURE"),
    (re.compile(r"\bbill(ing)?\b|\binvoice\b", re.I), "BILLING"),
    # Specific-before-general: a "change my shipping address" message must
    # match ADDRESS_CHANGE, not the broader SHIPPING pattern below it.
    (re.compile(r"\b(change|update)\b.*\baddress\b|\bshipping address\b", re.I), "ADDRESS_CHANGE"),
    (re.compile(r"\bship(ping|ment)?\b", re.I), "SHIPPING"),
    (re.compile(r"\bexchange\b", re.I), "EXCHANGE"),
    (re.compile(r"\breturn\b", re.I), "RETURNS"),
    (re.compile(r"\bcrash|error|bug|doesn'?t work|not working\b", re.I), "TECHNICAL_SUPPORT"),
    (re.compile(r"\baccount (access|locked|lockout)\b", re.I), "ACCOUNT_ACCESS"),
    (
        re.compile(r"\bcontacted support (three|3|multiple|several) times|nobody has (fixed|helped)\b", re.I),
        "COMPLAINT",
    ),
    (re.compile(r"\bwish|would be nice|feature request|please add\b", re.I), "FEATURE_REQUEST"),
    (re.compile(r"\bwhat information do you (collect|store)|privacy\b", re.I), "PRIVACY"),
    (re.compile(r"\blegal|lawsuit|attorney\b", re.I), "LEGAL"),
    (re.compile(r"\bwhat is|how does|tell me about|product\b", re.I), "PRODUCT_INFORMATION"),
]

_ANGRY_RE = re.compile(
    r"\b(angry|furious|ridiculous|unacceptable|worst|terrible|three times|again and again)\b", re.I
)
_URGENT_RE = re.compile(r"\burgent|asap|immediately|right now\b", re.I)
_DISTRESSED_RE = re.compile(r"\bscared|worried|panicking|help me please\b", re.I)
_FRUSTRATED_RE = re.compile(r"\bfrustrat|annoyed|not happy|disappointed\b", re.I)
_POSITIVE_RE = re.compile(r"\bthank|great|awesome|appreciate\b", re.I)


def _latest_user_content(messages: list[LLMMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content
    return messages[-1].content if messages else ""


def _classify_intent(text: str) -> str:
    for pattern, intent in _KEYWORD_INTENTS:
        if pattern.search(text):
            return intent
    return "UNKNOWN"


def _classify_sentiment(text: str) -> str:
    if _ANGRY_RE.search(text):
        return "ANGRY"
    if _URGENT_RE.search(text):
        return "URGENT"
    if _DISTRESSED_RE.search(text):
        return "DISTRESSED"
    if _FRUSTRATED_RE.search(text):
        return "FRUSTRATED"
    if _POSITIVE_RE.search(text):
        return "POSITIVE"
    return "NEUTRAL"


_FACTS_BLOCK_RE = re.compile(r"VERIFIED FACTS:\n((?:- .*\n?)+)", re.I)


def _extract_facts(system_text: str) -> list[str]:
    match = _FACTS_BLOCK_RE.search(system_text)
    if not match:
        return []
    return [line[2:].strip() for line in match.group(1).strip().splitlines() if line.startswith("- ")]


class MockLLMProvider:
    """Implements the LLMProvider protocol without any network calls.

    `generate()` deliberately surfaces the VERIFIED FACTS given to it
    verbatim (rather than inventing prose around them) - this both keeps it
    trivially grounded for check_grounding, and makes fact text like a
    confirmation question actually appear in the assistant's reply so
    downstream logic (e.g. detecting that the customer just confirmed a
    pending action) has something real to look at.
    """

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> str:
        await self._report_zero_cost_usage(usage_callback)
        system_text = next((m.content for m in messages if m.role == "system"), "")
        facts = _extract_facts(system_text)
        if not facts:
            text = _latest_user_content(messages)
            return (
                "Thanks for reaching out. I don't have verified information for this "
                f"request yet: '{text[:200]}'."
            )
        return " ".join(facts)

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> T:
        await self._report_zero_cost_usage(usage_callback)
        text = _latest_user_content(messages)
        name = schema.__name__
        builder = _STRUCTURED_BUILDERS.get(name)
        if builder is None:
            raise ValueError(f"MockLLMProvider has no builder registered for schema {name}")
        return schema.model_validate(builder(text))

    @staticmethod
    async def _report_zero_cost_usage(usage_callback: UsageCallback | None) -> None:
        # Exercises the cost-tracking pipeline in tests/offline dev without
        # implying any real spend - see app.llm.base.TokenUsage.
        if usage_callback is None:
            return
        maybe_awaitable = usage_callback(
            TokenUsage(provider="mock", model="mock", input_tokens=0, output_tokens=0, estimated_cost_usd=0.0)
        )
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable


def _build_intent_classification(text: str) -> dict:
    intent = _classify_intent(text)
    from app.domain.enums.intent import DATA_REQUIRED_INTENTS

    requires_data = intent in {i.value for i in DATA_REQUIRED_INTENTS}
    requires_human = intent in {"SECURITY", "FRAUD", "LEGAL"}
    return {
        "intent": intent,
        "confidence": 0.55 if intent == "UNKNOWN" else 0.92,
        "reasoning_summary": f"keyword match for intent={intent}",
        "requires_customer_data": requires_data,
        "requires_tool": requires_data,
        "requires_human": requires_human,
    }


def _build_priority_classification(text: str) -> dict:
    intent = _classify_intent(text)
    sentiment = _classify_sentiment(text)
    if intent in {"SECURITY", "FRAUD"}:
        priority = "CRITICAL"
    elif intent in {"PAYMENT_FAILURE", "LEGAL"} or sentiment == "ANGRY":
        priority = "HIGH"
    elif sentiment in {"URGENT", "DISTRESSED", "FRUSTRATED"}:
        priority = "MEDIUM"
    else:
        priority = "LOW" if intent in {"PRODUCT_INFORMATION", "FEATURE_REQUEST"} else "MEDIUM"
    return {
        "priority": priority,
        "reasoning_summary": f"derived from intent={intent}, sentiment={sentiment}",
    }


def _build_sentiment_detection(text: str) -> dict:
    return {"sentiment": _classify_sentiment(text)}


def _build_policy_check(text: str) -> dict:
    return {"approved": True, "violations": [], "severity": "none", "requires_human": False}


def _build_grounding_check(text: str) -> dict:
    return {"grounded": True, "ungrounded_claims": [], "confidence": 0.9}


def _build_response_review(text: str) -> dict:
    return {"approved": True, "issues": [], "revised_response": None}


def _build_commerce_eligibility(text: str) -> dict:
    # spec: Phase 12 - like _build_external_tool_selection below, this
    # judgment (does this specific order comply with this specific policy
    # text under today's date) needs real reasoning over free text, not
    # keyword matching against a fixed pattern list. The mock always
    # defers rather than fabricate a policy verdict; app.agents.policy_check
    # treats "insufficient_data" as "proceed exactly as before this
    # feature existed", so every MOCK_LLM=true flow is unaffected. Real
    # allow/deny behavior needs MOCK_LLM=false or a test-local stub LLM
    # (see tests/unit/test_policy_check.py).
    return {"qualifies": "insufficient_data", "reason": "mock provider does not evaluate policy text"}


def _build_external_tool_selection(text: str) -> dict:
    # Picking a real tool out of a dynamic, admin-configured catalog needs
    # actual reasoning about the tool's description vs. the customer's
    # message - keyword matching against a fixed pattern list (as the other
    # builders do) isn't meaningful here, so the mock always declines
    # rather than pretend to select. The external-tool fallback is
    # exercisable offline via direct unit tests of app.agents.external_tools
    # with a stub LLM; end-to-end tool *selection* needs MOCK_LLM=false (a
    # real provider).
    return {"tool_index": -1, "arguments": {}, "rationale": "mock provider does not select external tools"}


_STRUCTURED_BUILDERS = {
    "IntentClassification": _build_intent_classification,
    "PriorityClassification": _build_priority_classification,
    "SentimentDetection": _build_sentiment_detection,
    "PolicyCheck": _build_policy_check,
    "GroundingCheck": _build_grounding_check,
    "ResponseReview": _build_response_review,
    "ExternalToolSelection": _build_external_tool_selection,
    "CommerceEligibilityCheck": _build_commerce_eligibility,
}
