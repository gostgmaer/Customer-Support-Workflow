"""Shared LangChain-backed provider implementation.

Every real provider (Google, xAI, Anthropic, and any future OpenAI/Azure/
Bedrock/Ollama/OpenRouter addition per spec §3) is just a LangChain
`BaseChatModel` wired up with an API key and model name - the actual
generate()/generate_structured() logic is identical across all of them.
Factoring it here is what makes adding a new provider a ~15-line file (see
google.py/xai.py/anthropic.py) instead of copy-pasting this class each time.

Structured output goes through LangChain's `with_structured_output(schema,
include_raw=True)`, which for tool-calling-capable models is a forced
single-tool-call under the hood: the Pydantic schema becomes a tool
definition and the model is forced to call it, yielding a validated result
without relying on the model to "promise" JSON in free text.
`include_raw=True` is what makes the raw `AIMessage` (carrying
`usage_metadata`, spec §42) available alongside the parsed result.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.domain.exceptions import LLMError
from app.llm.base import LLMMessage, TokenUsage, UsageCallback
from app.llm.pricing import estimate_cost_usd
from app.observability.logging import get_logger
from app.observability.metrics import LLM_LATENCY
from app.observability.retry import with_retry

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_ROLE_TO_MESSAGE = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}


def to_langchain_messages(messages: list[LLMMessage]) -> list[BaseMessage]:
    return [_ROLE_TO_MESSAGE[m.role](content=m.content) for m in messages]


def _extract_text(content: Any) -> str:
    """`AIMessage.content` is a plain string for most providers, but
    newer Gemini responses (and any provider returning "content blocks")
    return a list instead - each item either a string or a dict, and not
    every dict carries text: Gemini's "thought signature" blocks (used to
    preserve reasoning continuity across a multi-turn tool-calling
    exchange) carry only a `signature`/`extras` payload with no `text` at
    all. Blindly `str()`-ing the whole list (the previous behavior) leaked
    that internal structure - including signature blobs - directly into
    the customer-facing response instead of just the actual reply text."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


async def _report_usage(
    usage_callback: UsageCallback | None, *, provider: str, model: str, ai_message: AIMessage | None
) -> None:
    if usage_callback is None or ai_message is None:
        return
    usage = getattr(ai_message, "usage_metadata", None)
    input_tokens = usage.get("input_tokens", 0) if usage else 0
    output_tokens = usage.get("output_tokens", 0) if usage else 0
    try:
        maybe_awaitable = usage_callback(
            TokenUsage(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimate_cost_usd(
                    model, input_tokens=input_tokens, output_tokens=output_tokens
                ),
            )
        )
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:  # noqa: BLE001
        # Cost tracking must never break an otherwise-successful LLM call.
        logger.warning("usage_callback_failed", provider=provider, model=model)


class LangChainChatProvider:
    """`LLMProvider` implementation backed by any LangChain `BaseChatModel`."""

    def __init__(self, provider_name: str, chat_model_factory: Callable[[int], BaseChatModel]) -> None:
        self._provider_name = provider_name
        self._factory = chat_model_factory

    @staticmethod
    def _model_name(chat: BaseChatModel) -> str:
        model = getattr(chat, "model", None) or getattr(chat, "model_name", "")
        return str(model)

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> str:
        chat = self._factory(max_tokens)
        lc_messages = to_langchain_messages(messages)

        async def _call() -> AIMessage:
            with LLM_LATENCY.labels(operation=f"{self._provider_name}.generate").time():
                return await chat.ainvoke(lc_messages)

        try:
            response = await with_retry(_call)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{self._provider_name} generate() failed: {exc}") from exc

        await _report_usage(
            usage_callback,
            provider=self._provider_name,
            model=self._model_name(chat),
            ai_message=response,
        )
        return _extract_text(response.content)

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> T:
        chat = self._factory(max_tokens)
        structured_chat = chat.with_structured_output(schema, include_raw=True)
        lc_messages = to_langchain_messages(messages)

        async def _call() -> dict[str, Any]:
            with LLM_LATENCY.labels(operation=f"{self._provider_name}.generate_structured").time():
                raw_result = await structured_chat.ainvoke(lc_messages)
                # include_raw=True guarantees a dict at runtime; the return
                # type is a union only because the same Runnable type is
                # shared with the include_raw=False case.
                assert isinstance(raw_result, dict)
                return raw_result

        try:
            result = await with_retry(_call)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"{self._provider_name} generate_structured() failed: {exc}") from exc

        await _report_usage(
            usage_callback,
            provider=self._provider_name,
            model=self._model_name(chat),
            ai_message=result.get("raw"),
        )
        parsed = result.get("parsed")
        if not isinstance(parsed, schema):
            raise LLMError(
                f"{self._provider_name} structured output did not match {schema.__name__}: "
                f"{result.get('parsing_error')}"
            )
        return parsed
