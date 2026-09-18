"""Provider contract tests (spec §47): every adapter (mock, google, xai,
anthropic) must satisfy the same `LLMProvider` contract - generate()
returns a string, generate_structured() returns an instance of the
requested schema, and usage is reported via `usage_callback` - so
providers can be swapped without changing business logic. Real
Google/xAI/Anthropic chat models are replaced with a fake `BaseChatModel`
stand-in (no network calls); MockLLMProvider is exercised directly since
it doesn't wrap a LangChain chat model at all.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.agents.schemas import PolicyCheck
from app.llm.base import LLMMessage, TokenUsage
from app.llm.providers.anthropic import AnthropicLLMProvider
from app.llm.providers.google import GoogleLLMProvider
from app.llm.providers.mock import MockLLMProvider
from app.llm.providers.xai import XAILLMProvider

# PolicyCheck (rather than a throwaway test-only schema) so MockLLMProvider
# - which only knows the real schemas registered in its
# _STRUCTURED_BUILDERS - can participate in the same contract test as the
# LangChain-backed providers (which can satisfy any schema via the fake
# chat model below).
_SCHEMA = PolicyCheck


_FAKE_AI_MESSAGE = AIMessage(
    content="fake response", usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
)


class _FakeStructuredRunnable:
    def __init__(self, schema: type[BaseModel]) -> None:
        self._schema = schema

    async def ainvoke(self, messages):  # noqa: ANN001
        return {"raw": _FAKE_AI_MESSAGE, "parsed": self._schema.model_construct(), "parsing_error": None}


class _FakeChatModel:
    model = "fake-model-for-contract-test"

    async def ainvoke(self, messages):  # noqa: ANN001
        return _FAKE_AI_MESSAGE

    def with_structured_output(self, schema: type[BaseModel], include_raw: bool = False):
        return _FakeStructuredRunnable(schema)


def _langchain_backed_provider(provider_class):
    """Google/xAI/Anthropic providers all take (api_key, model) and build a
    LangChain chat model via an internal `_factory` - swap that factory for
    the fake above so no network call happens."""
    provider = provider_class("fake-key", "fake-model")
    provider._factory = lambda max_tokens: _FakeChatModel()  # noqa: SLF001
    return provider


@pytest.fixture(
    params=["mock", "google", "xai", "anthropic"],
)
def provider(request):
    if request.param == "mock":
        return MockLLMProvider()
    return _langchain_backed_provider(
        {"google": GoogleLLMProvider, "xai": XAILLMProvider, "anthropic": AnthropicLLMProvider}[
            request.param
        ]
    )


@pytest.mark.asyncio
async def test_generate_returns_a_string(provider):
    result = await provider.generate([LLMMessage(role="user", content="hello")])
    assert isinstance(result, str)
    assert result


@pytest.mark.asyncio
async def test_generate_structured_returns_the_requested_schema(provider):
    result = await provider.generate_structured(
        [LLMMessage(role="system", content="be helpful"), LLMMessage(role="user", content="hello")],
        schema=_SCHEMA,
    )
    assert isinstance(result, _SCHEMA)


@pytest.mark.asyncio
async def test_generate_reports_usage_via_callback(provider):
    reported: list[TokenUsage] = []

    async def _capture(usage: TokenUsage) -> None:
        reported.append(usage)

    await provider.generate([LLMMessage(role="user", content="hello")], usage_callback=_capture)

    assert len(reported) == 1
    assert reported[0].input_tokens >= 0
    assert reported[0].output_tokens >= 0
    assert reported[0].estimated_cost_usd >= 0.0


@pytest.mark.asyncio
async def test_generate_structured_reports_usage_via_callback(provider):
    reported: list[TokenUsage] = []

    def _capture(usage: TokenUsage) -> None:  # sync callback must also work, not only async
        reported.append(usage)

    await provider.generate_structured(
        [LLMMessage(role="user", content="hello")], schema=_SCHEMA, usage_callback=_capture
    )

    assert len(reported) == 1
