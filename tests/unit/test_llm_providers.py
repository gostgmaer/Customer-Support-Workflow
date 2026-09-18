"""No network calls here - just guards against LangChain chat-model
constructor kwarg drift (langchain_google_genai/langchain_xai/langchain_anthropic
have all changed field names across versions), since these paths aren't
otherwise exercised by the mock-provider-based tests.
"""

import pytest
from langchain_core.messages import AIMessage

from app.llm.base import LLMMessage
from app.llm.providers._langchain_base import _extract_text, to_langchain_messages
from app.llm.providers.anthropic import AnthropicLLMProvider
from app.llm.providers.google import GoogleLLMProvider
from app.llm.providers.xai import XAILLMProvider


def test_google_chat_model_constructs_with_expected_fields():
    provider = GoogleLLMProvider(api_key="fake", model="gemini-2.5-flash")
    chat = provider._factory(256)
    assert chat.model == "gemini-2.5-flash"
    assert chat.max_output_tokens == 256


def test_xai_chat_model_constructs_with_expected_fields():
    provider = XAILLMProvider(api_key="fake", model="grok-4-fast")
    chat = provider._factory(256)
    assert chat.model_name == "grok-4-fast"
    assert chat.max_tokens == 256


def test_anthropic_chat_model_constructs_with_expected_fields():
    provider = AnthropicLLMProvider(api_key="sk-test-fake", model="claude-sonnet-5")
    chat = provider._factory(256)
    assert chat.model == "claude-sonnet-5"
    assert chat.max_tokens == 256


def test_message_role_mapping():
    messages = [
        LLMMessage(role="system", content="be helpful"),
        LLMMessage(role="user", content="hi"),
        LLMMessage(role="assistant", content="hello"),
    ]
    lc_messages = to_langchain_messages(messages)
    assert [m.type for m in lc_messages] == ["system", "human", "ai"]
    assert lc_messages[1].content == "hi"


def test_extract_text_passes_through_a_plain_string():
    assert _extract_text("hello there") == "hello there"


def test_extract_text_joins_text_blocks_and_drops_signature_only_blocks():
    # Regression test: real Gemini responses (gemini-3.x) can return
    # `AIMessage.content` as a list of blocks rather than a plain string -
    # including a signature-only block (no "text" key at all) used to
    # preserve reasoning continuity across a multi-turn tool-calling
    # exchange. The previous code (`str(content)` on anything non-string)
    # leaked that whole structure - dict syntax, signature blob included -
    # directly into the customer-facing response.
    content = [
        {"type": "text", "text": "Here is the answer: "},
        {"type": "text", "text": "42."},
        {"extras": {"signature": "EnEKbwERTTlPRGLhmG31yuFytsA+LlODX3muVxlyETAcCjD8585qHFxyBHxlQZwdE"}},
    ]
    assert _extract_text(content) == "Here is the answer: 42."


def test_extract_text_handles_plain_string_list_items():
    assert _extract_text(["part one ", "part two"]) == "part one part two"


@pytest.mark.asyncio
async def test_generate_extracts_text_from_gemini_style_block_content():
    """End-to-end through GoogleLLMProvider.generate() - not just the
    helper in isolation - since this is exactly the path that produced a
    broken customer-facing message during live testing with a real
    gemini-3.1-flash-lite response."""
    ai_message = AIMessage(
        content=[
            {"type": "text", "text": "I checked and "},
            {"type": "text", "text": "Hooks let you use state in function components."},
            {"extras": {"signature": "some-thought-signature"}},
        ],
        usage_metadata={"input_tokens": 10, "output_tokens": 12, "total_tokens": 22},
    )

    class _FakeChatModel:
        model = "gemini-3.1-flash-lite"

        async def ainvoke(self, messages):  # noqa: ANN001
            return ai_message

    provider = GoogleLLMProvider(api_key="fake", model="gemini-3.1-flash-lite")
    provider._factory = lambda max_tokens: _FakeChatModel()  # noqa: SLF001

    result = await provider.generate([LLMMessage(role="user", content="how do hooks work?")])

    assert result == "I checked and Hooks let you use state in function components."
    assert "signature" not in result
