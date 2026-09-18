"""Structured outputs shared by the agents (spec §5, §6, §7, §15, §16)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.enums.intent import Intent

# spec: Phase 9.2 - previously a bare `str`, meaning the model was asked
# to classify into a taxonomy that was never actually shown to it
# anywhere (the prompt just said "from the allowed list" - see
# app.agents.classifier's _INTENT_SYSTEM_RULES). Building this from the
# real Intent enum turns it into a genuine JSON-schema `enum` constraint
# once passed through LangChain's with_structured_output
# (app.llm.providers._langchain_base) - the model is now actually
# constrained to a real value, not just asked nicely. `Literal[tuple(...)]`
# is deliberate, not a typo - passing a tuple to Literal.__class_getitem__
# unpacks it exactly like `Literal[*values]` (verified against this
# project's installed Python/pydantic before relying on it), and building
# it from the enum means this can never silently drift out of sync with
# `Intent` again the way it did for four phases after Phase 8.3 added
# new members but nothing here or in the prompt ever mentioned them.
_INTENT_VALUES = tuple(i.value for i in Intent)


class IntentClassification(BaseModel):
    intent: Literal[_INTENT_VALUES]  # type: ignore[valid-type]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str
    requires_customer_data: bool
    requires_tool: bool
    requires_human: bool


class PriorityClassification(BaseModel):
    priority: str
    reasoning_summary: str = ""


class SentimentDetection(BaseModel):
    sentiment: str


class PolicyCheck(BaseModel):
    approved: bool
    violations: list[str] = Field(default_factory=list)
    severity: str = "none"
    requires_human: bool = False


class GroundingCheck(BaseModel):
    grounded: bool
    ungrounded_claims: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class ResponseReview(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    revised_response: str | None = None


class ExternalToolSelection(BaseModel):
    """Structured-output schema for app.agents.external_tools' bounded
    tool-selection fallback (spec: Phase 6 MCP integration, Phase 7
    generalized to also cover OpenAPI-described REST APIs). The model
    picks at most one tool by its position in the catalog it was shown
    (`tool_index`), never a freeform name - this keeps the choice
    constrained to what's actually connected, per rule 17 (prefer
    deterministic logic over autonomous LLM decisions: the LLM only
    narrows a small, admin-configured menu, it never decides to act)."""

    tool_index: int = -1  # -1 = no listed tool directly helps
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
