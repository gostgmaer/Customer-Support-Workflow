"""classify_intent / classify_priority / detect_sentiment nodes (spec §5-7, §30)."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from app.agents.classifier import (
    classify_intent,
    classify_priority,
    detect_sentiment,
    sentiment_escalates_priority,
)
from app.agents.confirmation import (
    CONFIRMATION_CAPABLE_INTENTS,
    interpret_confirmation_reply,
    last_assistant_asked_to_confirm,
)
from app.domain.enums.priority import PRIORITY_ORDER, Priority
from app.observability.metrics import INTENT_CLASSIFICATIONS
from app.security.pii import redact
from app.workflow.deps import get_deps
from app.workflow.state import SupportState


async def classify_intent_node(state: SupportState, config: RunnableConfig) -> dict:
    # A short reply like "yes" or "go ahead" carries none of the original
    # request's keywords. Rather than let the classifier guess (and likely
    # land on UNKNOWN, derailing a pending refund/cancel/subscription
    # confirmation), deterministically keep the previous turn's intent
    # whenever the assistant just asked to confirm something and this
    # message reads as a yes/no reply (rule 17: prefer deterministic logic).
    previous_intent = state.get("previous_intent")
    history = state.get("messages", [])
    if (
        previous_intent in CONFIRMATION_CAPABLE_INTENTS
        and last_assistant_asked_to_confirm(history)
        and interpret_confirmation_reply(state["latest_message"]) is not None
    ):
        return {"intent": previous_intent, "intent_confidence": 1.0, "requires_human": False}

    deps = get_deps(config)
    llm = deps.llm_router.get_model("intent_classification")
    result = await classify_intent(llm, redact(state["latest_message"]))
    INTENT_CLASSIFICATIONS.labels(intent=result.intent).inc()
    return {
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "requires_human": result.requires_human,
    }


async def classify_priority_node(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    llm = deps.llm_router.get_model("priority_classification")
    result = await classify_priority(
        llm, redact(state["latest_message"]), intent=(state.get("intent") or "UNKNOWN")
    )
    return {"priority": result.priority}


async def detect_sentiment_node(state: SupportState, config: RunnableConfig) -> dict:
    deps = get_deps(config)
    llm = deps.llm_router.get_model("sentiment_detection")
    result = await detect_sentiment(llm, redact(state["latest_message"]))

    priority = (state.get("priority") or Priority.MEDIUM.value)
    if sentiment_escalates_priority(result.sentiment):
        current_rank = PRIORITY_ORDER.get(Priority(priority), 1)
        bumped = Priority.HIGH if current_rank < PRIORITY_ORDER[Priority.HIGH] else Priority(priority)
        priority = bumped.value

    return {"sentiment": result.sentiment, "priority": priority}
