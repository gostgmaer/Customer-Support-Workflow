"""Google Gemini provider (default primary - spec §3)."""

from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI

from app.llm.providers._langchain_base import LangChainChatProvider


class GoogleLLMProvider(LangChainChatProvider):
    def __init__(self, api_key: str, model: str) -> None:
        def factory(max_tokens: int) -> ChatGoogleGenerativeAI:
            return ChatGoogleGenerativeAI(
                model=model, google_api_key=api_key, max_output_tokens=max_tokens
            )

        super().__init__("google", factory)
