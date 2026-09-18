"""app.agents.classifier.classify_intent (spec: Phase 9.2) - the root
cause of a real, previously-unfixed bug: the prompt sent to the model
never once named any of the real Intent enum values, and the schema
field accepting the answer was a bare `str` with no enum constraint.
Three separate live-testing incidents (an order-id-shaped token in the
message misclassifying as UNKNOWN) were each logged as "a live-testing
finding," cross-referenced as "the same variance," and never
root-caused. These tests prove the actual fix - the taxonomy is now in
the prompt text and the schema is enum-constrained - and the bounded
retry/fallback behavior around it.
"""

from __future__ import annotations

from app.agents.classifier import _INTENT_SYSTEM_RULES, classify_intent
from app.agents.schemas import IntentClassification
from app.domain.enums.intent import Intent
from app.domain.exceptions import LLMError
from app.llm.base import LLMMessage, UsageCallback


def test_intent_system_rules_names_every_intent_value():
    """Structural regression test: makes the taxonomy silently drifting
    out of the prompt again (as it did across Phase 8.3 adding four new
    intents that this prompt never mentioned) impossible to reintroduce
    unnoticed."""
    for intent in Intent:
        assert intent.value in _INTENT_SYSTEM_RULES


class _ScriptedLLM:
    """Returns each entry in `responses` in order on successive
    generate_structured calls - either an IntentClassification, or an
    exception instance to raise (simulating a schema-validation failure
    LangChain's with_structured_output would surface as an LLMError)."""

    def __init__(self, responses: list[IntentClassification | Exception]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def generate(
        self, messages: list[LLMMessage], *, max_tokens: int = 1024, usage_callback=None
    ) -> str:
        raise NotImplementedError

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ):
        assert schema is IntentClassification
        self.call_count += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _classification(intent: str) -> IntentClassification:
    return IntentClassification(
        intent=intent,
        confidence=0.9,
        reasoning_summary="test",
        requires_customer_data=False,
        requires_tool=False,
        requires_human=False,
    )


async def test_correct_first_try_makes_exactly_one_call():
    llm = _ScriptedLLM([_classification("ORDER_STATUS")])

    result = await classify_intent(llm, "Where is my order ORD-9001?")

    assert result.intent == "ORDER_STATUS"
    assert llm.call_count == 1


async def test_unknown_first_try_retries_once_and_recovers():
    llm = _ScriptedLLM([_classification("UNKNOWN"), _classification("EXCHANGE")])

    result = await classify_intent(llm, "I'd like to exchange order ORD-1002 for a different size.")

    assert result.intent == "EXCHANGE"
    assert llm.call_count == 2


async def test_unknown_both_tries_falls_back_to_unknown_without_raising():
    llm = _ScriptedLLM([_classification("UNKNOWN"), _classification("UNKNOWN")])

    result = await classify_intent(llm, "asdkjqwoeiruqwoe")

    assert result.intent == "UNKNOWN"
    assert llm.call_count == 2


async def test_schema_validation_failure_retries_then_falls_back_safely():
    """A provider that doesn't strictly enforce the enum constraint could
    still return an out-of-taxonomy string - LangChain surfaces that as
    an LLMError from generate_structured, not an invalid
    IntentClassification. This must never propagate out of
    classify_intent and take down the workflow run - it must fail safe
    to UNKNOWN, matching this codebase's escalate-rather-than-crash
    posture for every other classification failure mode."""
    llm = _ScriptedLLM([LLMError("schema mismatch"), LLMError("schema mismatch again")])

    result = await classify_intent(llm, "some message")

    assert result.intent == "UNKNOWN"
    assert result.requires_human is False
    assert llm.call_count == 2


async def test_schema_validation_failure_then_success_on_retry():
    llm = _ScriptedLLM([LLMError("schema mismatch"), _classification("REFUND")])

    result = await classify_intent(llm, "I want my money back")

    assert result.intent == "REFUND"
    assert llm.call_count == 2


async def test_always_escalate_intent_sets_requires_human():
    llm = _ScriptedLLM([_classification("SECURITY")])

    result = await classify_intent(llm, "someone accessed my account")

    assert result.requires_human is True
