"""app.llm.router / app.llm.factory / app.llm.health (spec §6-8).

Uses fake providers registered directly into the factory's builder table so
failover/health behavior is tested deterministically without real API keys
or network calls.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from app.config import get_settings
from app.domain.exceptions import LLMError
from app.llm.base import LLMMessage
from app.llm.factory import _BUILDERS, get_provider, reset_provider_cache
from app.llm.health import get_health_registry
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter


class _AlwaysSucceeds:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls = 0

    async def generate(self, messages, *, max_tokens=1024, usage_callback=None):
        self.calls += 1
        return self.label

    async def generate_structured(self, messages, *, schema, max_tokens=1024, usage_callback=None):
        self.calls += 1
        raise NotImplementedError


class _AlwaysFails:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls = 0

    async def generate(self, messages, *, max_tokens=1024, usage_callback=None):
        self.calls += 1
        raise LLMError(f"{self.label} is down")

    async def generate_structured(self, messages, *, schema, max_tokens=1024, usage_callback=None):
        self.calls += 1
        raise LLMError(f"{self.label} is down")


@contextmanager
def real_providers_enabled(monkeypatch, *, primary, fallback):
    """Registers `primary`/`fallback` fakes as DEFAULT/FALLBACK_LLM_PROVIDER
    with MOCK_LLM off, and restores the mock-mode test default afterward."""
    monkeypatch.setitem(_BUILDERS, "fake_primary", lambda: primary)
    monkeypatch.setitem(_BUILDERS, "fake_fallback", lambda: fallback)
    os.environ["MOCK_LLM"] = "false"
    os.environ["DEFAULT_LLM_PROVIDER"] = "fake_primary"
    os.environ["FALLBACK_LLM_PROVIDER"] = "fake_fallback"
    get_settings.cache_clear()
    reset_provider_cache()
    get_health_registry().reset()
    try:
        yield
    finally:
        os.environ["MOCK_LLM"] = "true"
        os.environ.pop("DEFAULT_LLM_PROVIDER", None)
        os.environ.pop("FALLBACK_LLM_PROVIDER", None)
        get_settings.cache_clear()
        reset_provider_cache()
        get_health_registry().reset()


def test_mock_mode_returns_mock_for_any_purpose():
    router = LLMRouter()
    for purpose in ("intent_classification", "resolution_response", "policy_check", "made_up_purpose"):
        assert isinstance(router.get_model(purpose), MockLLMProvider)


@pytest.mark.asyncio
async def test_router_uses_primary_when_healthy(monkeypatch):
    primary, fallback = _AlwaysSucceeds("primary"), _AlwaysSucceeds("fallback")
    with real_providers_enabled(monkeypatch, primary=primary, fallback=fallback):
        result = await LLMRouter().get_model("resolution_response").generate(
            [LLMMessage(role="user", content="hi")]
        )
    assert result == "primary"
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_router_fails_over_to_fallback_on_primary_error(monkeypatch):
    primary, fallback = _AlwaysFails("primary"), _AlwaysSucceeds("fallback")
    with real_providers_enabled(monkeypatch, primary=primary, fallback=fallback):
        result = await LLMRouter().get_model("resolution_response").generate(
            [LLMMessage(role="user", content="hi")]
        )
    assert result == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_reasoning_purpose_fails_over_to_default_provider(monkeypatch):
    """Regression test: "reasoning" purposes (policy_check/grounding_check/
    response_review) use the fallback_provider as their PRIMARY (spec §5:
    "reasoning -> xai/Grok"), which used to make LLMRouter.get_model
    compute a "fallback candidate" that was the *same* provider as
    primary for these purposes - _FailoverLLMProvider._candidates() then
    silently dropped it as a duplicate, leaving a reasoning-purpose call
    with nowhere to fail over to at all (contradicting spec §6's
    "Retry -> Fallback Provider -> Safe fallback/Human") whenever the
    fallback_provider (e.g. xai) was unavailable/misconfigured - exactly
    what happened live with a real Google key configured but no xai key."""
    primary, fallback = _AlwaysSucceeds("primary"), _AlwaysFails("fallback")
    with real_providers_enabled(monkeypatch, primary=primary, fallback=fallback):
        result = await LLMRouter().get_model("policy_check").generate(
            [LLMMessage(role="user", content="hi")]
        )
    assert result == "primary"
    assert fallback.calls == 1
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_router_raises_when_both_providers_fail(monkeypatch):
    primary, fallback = _AlwaysFails("primary"), _AlwaysFails("fallback")
    with real_providers_enabled(monkeypatch, primary=primary, fallback=fallback):
        with pytest.raises(LLMError):
            await LLMRouter().get_model("resolution_response").generate(
                [LLMMessage(role="user", content="hi")]
            )


def test_factory_raises_clear_error_for_unconfigured_provider():
    with pytest.raises(LLMError):
        get_provider("google")  # no GOOGLE_API_KEY set in the test environment


def test_factory_raises_for_unknown_provider():
    with pytest.raises(LLMError):
        get_provider("not_a_real_provider")


def test_health_registry_disables_after_repeated_failures():
    registry = get_health_registry()
    for _ in range(6):
        registry.record_failure("some_provider")
    assert registry.is_disabled("some_provider")
    registry.record_success("some_provider")
    assert not registry.is_disabled("some_provider")
