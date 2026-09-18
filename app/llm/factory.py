"""Builds a concrete `LLMProvider` for a given provider name (spec §3-4).

Adding a new provider: write a class in `app/llm/providers/<name>.py`
following `google.py`/`xai.py`/`anthropic.py` (each is ~15 lines - a
`LangChainChatProvider` wrapping one LangChain `BaseChatModel`), then
register it in `_BUILDERS` below. Nothing else in the codebase needs to
change - callers only ever ask the router for a model "by purpose"
(see `app.llm.router`).
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import get_settings
from app.domain.exceptions import LLMError
from app.llm.base import LLMProvider

_BUILDERS: dict[str, Callable[[], LLMProvider]] = {}


def _build_google() -> LLMProvider:
    from app.llm.providers.google import GoogleLLMProvider

    settings = get_settings()
    if not settings.google_api_key:
        raise LLMError("GOOGLE_API_KEY is not configured", details={"provider": "google"})
    return GoogleLLMProvider(settings.google_api_key, settings.google_model)


def _build_xai() -> LLMProvider:
    from app.llm.providers.xai import XAILLMProvider

    settings = get_settings()
    if not settings.xai_api_key:
        raise LLMError("XAI_API_KEY is not configured", details={"provider": "xai"})
    return XAILLMProvider(settings.xai_api_key, settings.xai_model)


def _build_anthropic() -> LLMProvider:
    from app.llm.providers.anthropic import AnthropicLLMProvider

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not configured", details={"provider": "anthropic"})
    return AnthropicLLMProvider(settings.anthropic_api_key, settings.anthropic_model)


def _build_mock() -> LLMProvider:
    from app.llm.providers.mock import MockLLMProvider

    return MockLLMProvider()


_BUILDERS.update(google=_build_google, xai=_build_xai, anthropic=_build_anthropic, mock=_build_mock)

_instances: dict[str, LLMProvider] = {}


def get_provider(provider_name: str) -> LLMProvider:
    """Returns a cached provider instance for `provider_name` (mock, google,
    xai, anthropic, ...). Raises LLMError if the provider is unknown or
    unconfigured (e.g. missing API key)."""
    if provider_name in _instances:
        return _instances[provider_name]

    builder = _BUILDERS.get(provider_name)
    if builder is None:
        raise LLMError(
            f"Unknown LLM provider '{provider_name}'",
            details={"known_providers": sorted(_BUILDERS)},
        )
    instance = builder()
    _instances[provider_name] = instance
    return instance


def reset_provider_cache() -> None:
    """Test-only: clears cached provider instances (e.g. after changing
    settings/env vars mid-test-session)."""
    _instances.clear()
