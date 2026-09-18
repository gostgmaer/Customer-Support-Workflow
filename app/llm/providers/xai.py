"""xAI Grok provider (default fallback - spec §3)."""

from __future__ import annotations

from langchain_xai import ChatXAI

from app.llm.providers._langchain_base import LangChainChatProvider


class XAILLMProvider(LangChainChatProvider):
    def __init__(self, api_key: str, model: str) -> None:
        def factory(max_tokens: int) -> ChatXAI:
            # ChatXAI's pydantic-generated __init__ isn't visible to mypy.
            return ChatXAI(model_name=model, xai_api_key=api_key, max_tokens=max_tokens)  # type: ignore[call-arg]

        super().__init__("xai", factory)
