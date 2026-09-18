"""Anthropic Claude provider (optional extra provider - spec §3)."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from app.llm.providers._langchain_base import LangChainChatProvider


class AnthropicLLMProvider(LangChainChatProvider):
    def __init__(self, api_key: str, model: str) -> None:
        def factory(max_tokens: int) -> ChatAnthropic:
            # ChatAnthropic's pydantic-generated __init__ isn't visible to mypy.
            return ChatAnthropic(  # type: ignore[call-arg]
                model=model, anthropic_api_key=api_key, max_tokens=max_tokens
            )

        super().__init__("anthropic", factory)
