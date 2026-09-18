"""LLM router (spec §6-7): the only thing the rest of the app talks to.

`get_llm_router().get_model(purpose)` resolves purpose -> profile -> a
provider+model pair (see `app.llm.profiles`), and returns a provider that
transparently retries on the primary, then fails over to the configured
fallback provider on failure - never on the *caller's* profile choice
(spec §6: "Retry -> Fallback Provider -> Safe fallback/Human"). Health
tracking (`app.llm.health`) means a provider that has been failing
repeatedly is skipped in favor of the fallback without even trying it.

`MOCK_LLM=true` (the zero-setup default, spec §48) short-circuits all of
this and returns the deterministic mock provider for every purpose.
"""

from __future__ import annotations

import inspect
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.config import get_settings
from app.domain.exceptions import LLMError
from app.llm.base import LLMMessage, LLMProvider, TokenUsage, UsageCallback
from app.llm.factory import get_provider
from app.llm.health import get_health_registry
from app.llm.profiles import PURPOSE_TO_PROFILE, ModelProfile, get_profiles
from app.observability.logging import get_logger

logger = get_logger(__name__)


class LLMRouterLike(Protocol):
    """What `app.workflow.deps.WorkflowDeps.llm_router` actually needs to
    support - satisfied by `LLMRouter`, `TenantScopedLLMRouter`, and
    `RecordingLLMRouter` alike, so any of them can wrap any other."""

    def get_model(self, purpose: str) -> LLMProvider: ...

T = TypeVar("T", bound=BaseModel)


class _FailoverLLMProvider:
    """Wraps a primary + fallback profile behind the single `LLMProvider`
    interface, so every call site sees one object regardless of how many
    providers are actually configured behind it."""

    def __init__(self, purpose: str, primary: ModelProfile, fallback: ModelProfile) -> None:
        self._purpose = purpose
        self._primary = primary
        self._fallback = fallback

    def _candidates(self) -> list[ModelProfile]:
        health = get_health_registry()
        candidates = [self._primary]
        if self._fallback.provider != self._primary.provider:
            candidates.append(self._fallback)
        # A disabled primary is skipped in favor of the fallback outright
        # (spec §8) rather than wasting a request/retry cycle on it first.
        candidates.sort(key=lambda p: health.is_disabled(p.provider))
        return candidates

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> str:
        health = get_health_registry()
        last_error: Exception | None = None
        for profile in self._candidates():
            try:
                provider = get_provider(profile.provider)
                result = await provider.generate(
                    messages, max_tokens=max_tokens, usage_callback=usage_callback
                )
                health.record_success(profile.provider)
                return result
            except Exception as exc:  # noqa: BLE001
                health.record_failure(profile.provider)
                logger.warning(
                    "llm_provider_failed",
                    purpose=self._purpose,
                    provider=profile.provider,
                    error=str(exc),
                )
                last_error = exc
        raise LLMError(
            f"All providers failed for purpose '{self._purpose}': {last_error}",
            details={"purpose": self._purpose},
        )

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> T:
        health = get_health_registry()
        last_error: Exception | None = None
        for profile in self._candidates():
            try:
                provider = get_provider(profile.provider)
                result = await provider.generate_structured(
                    messages, schema=schema, max_tokens=max_tokens, usage_callback=usage_callback
                )
                health.record_success(profile.provider)
                return result
            except Exception as exc:  # noqa: BLE001
                health.record_failure(profile.provider)
                logger.warning(
                    "llm_provider_failed",
                    purpose=self._purpose,
                    provider=profile.provider,
                    error=str(exc),
                )
                last_error = exc
        raise LLMError(
            f"All providers failed for purpose '{self._purpose}': {last_error}",
            details={"purpose": self._purpose},
        )


class LLMRouter:
    def get_model(
        self,
        purpose: str,
        *,
        mock_llm: bool | None = None,
        default_provider: str | None = None,
        fallback_provider: str | None = None,
    ) -> LLMProvider:
        """`mock_llm`/`default_provider`/`fallback_provider` let a caller
        override the env-var-derived choice for this one call (used by
        `TenantScopedLLMRouter` to apply a tenant's DB setting override,
        spec §43) - omitted, this behaves exactly as before."""
        settings = get_settings()
        if mock_llm if mock_llm is not None else settings.mock_llm:
            return get_provider("mock")

        profiles = get_profiles(default_provider, fallback_provider)
        profile_name = PURPOSE_TO_PROFILE.get(purpose, "default")
        primary = profiles[profile_name]
        # The failover candidate must be a genuinely different provider
        # from `primary`, not just "whichever profile is nominally called
        # 'fallback'". "reasoning" purposes (policy_check/grounding_check/
        # response_review) deliberately use the fallback_provider as their
        # *primary* (spec §5: "reasoning -> xai/Grok") - `profiles["reasoning"]`
        # and `profiles["fallback"]` are the same ModelProfile. Picking
        # `profiles["fallback"]` here for a "reasoning" purpose would pick
        # that same provider again, which _FailoverLLMProvider._candidates()
        # then silently drops as a duplicate - leaving reasoning calls with
        # *zero* real failover (contradicting spec §6's "Retry -> Fallback
        # Provider -> Safe fallback/Human") whenever xai is unavailable.
        # Always failing over to whichever provider `primary` *isn't*
        # handles every purpose correctly, including future profiles.
        other_provider_is_fallback = primary.provider != profiles["fallback"].provider
        fallback = profiles["fallback"] if other_provider_is_fallback else profiles["default"]
        return _FailoverLLMProvider(purpose, primary, fallback)  # type: ignore[return-value]


_router = LLMRouter()


def get_llm_router() -> LLMRouter:
    return _router


class TenantScopedLLMRouter:
    """Wraps `LLMRouter` so every `get_model()` call uses this tenant's
    resolved mock_llm/provider overrides (`app.config.dynamic_settings`,
    spec §43) - none of the ~9 `deps.llm_router.get_model(purpose)` call
    sites in `app/workflow/nodes/*.py` need to know overrides exist.
    Constructed once per request in `app.workflow.runner._build_deps`."""

    def __init__(
        self, inner: LLMRouter, *, mock_llm: bool, default_provider: str, fallback_provider: str
    ) -> None:
        self._inner = inner
        self._mock_llm = mock_llm
        self._default_provider = default_provider
        self._fallback_provider = fallback_provider

    def get_model(self, purpose: str) -> LLMProvider:
        return self._inner.get_model(
            purpose,
            mock_llm=self._mock_llm,
            default_provider=self._default_provider,
            fallback_provider=self._fallback_provider,
        )


async def _maybe_await(value: object) -> None:
    if inspect.isawaitable(value):
        await value


class _RecordingProviderProxy:
    """Wraps one `LLMProvider` so every call also reports usage to
    `on_usage`, on top of whatever `usage_callback` the caller itself
    passes (there isn't one today, but this stays composable)."""

    def __init__(self, inner: LLMProvider, on_usage: UsageCallback) -> None:
        self._inner = inner
        self._on_usage = on_usage

    def _combined(self, external: UsageCallback | None) -> UsageCallback:
        async def _callback(usage: TokenUsage) -> None:
            await _maybe_await(self._on_usage(usage))
            if external is not None:
                await _maybe_await(external(usage))

        return _callback

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> str:
        return await self._inner.generate(
            messages, max_tokens=max_tokens, usage_callback=self._combined(usage_callback)
        )

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> T:
        return await self._inner.generate_structured(
            messages, schema=schema, max_tokens=max_tokens, usage_callback=self._combined(usage_callback)
        )


class RecordingLLMRouter:
    """Wraps `LLMRouter` so every model obtained via `get_model()` reports
    its token usage to `on_usage` (spec §42) - used by
    `app.workflow.graph._traced` to record a `model_requests` row per LLM
    call without touching the 9 existing `deps.llm_router.get_model(...)`
    call sites in `app/workflow/nodes/*.py`."""

    def __init__(self, inner: LLMRouterLike, on_usage: UsageCallback) -> None:
        self._inner = inner
        self._on_usage = on_usage

    def get_model(self, purpose: str) -> LLMProvider:
        return _RecordingProviderProxy(self._inner.get_model(purpose), self._on_usage)  # type: ignore[return-value]
