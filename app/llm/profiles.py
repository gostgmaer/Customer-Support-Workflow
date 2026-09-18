"""Model profiles (spec §5): named provider+model pairs, resolved entirely
from configuration - never hard-coded in business logic.

`app.llm.router` maps each call site's *purpose* (e.g.
"intent_classification") to one of these profiles, and each profile to a
provider+model pair. Changing which vendor/model handles a purpose is a
config change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    model: str


def _model_for(provider: str) -> str:
    settings = get_settings()
    return {
        "google": settings.google_model,
        "xai": settings.xai_model,
        "anthropic": settings.anthropic_model,
    }.get(provider, "")


def get_profiles(
    default_provider: str | None = None, fallback_provider: str | None = None
) -> dict[str, ModelProfile]:
    """Built lazily (not at import time) so tests/config overrides that
    change env vars mid-process are picked up. `default_provider`/
    `fallback_provider` let a caller (app.llm.router.TenantScopedLLMRouter)
    override the env-var defaults with a tenant's DB setting override
    (spec §43) without this function needing to know DB overrides exist."""
    settings = get_settings()
    default_provider = default_provider or settings.default_llm_provider
    fallback_provider = fallback_provider or settings.fallback_llm_provider
    default = ModelProfile(default_provider, _model_for(default_provider))
    fallback = ModelProfile(fallback_provider, _model_for(fallback_provider))
    return {
        "default": default,
        "fallback": fallback,
        # Fast/cheap classification tasks stay on the default provider by
        # default; point PURPOSE_TO_PROFILE at a different profile (or add
        # a dedicated one here) if you want a smaller/cheaper model.
        "classification": default,
        # Deeper reasoning tasks (policy/grounding/review) default to the
        # fallback provider per spec §5's example (reasoning -> xai/Grok).
        "reasoning": fallback,
        "response": default,
    }


# Purpose -> profile name. Every LLM call site in app/agents/* requests a
# model by one of these purposes (app.llm.router.get_llm_router().get_model(purpose)).
PURPOSE_TO_PROFILE: dict[str, str] = {
    "intent_classification": "classification",
    "priority_classification": "classification",
    "sentiment_detection": "classification",
    "resolution_response": "response",
    "policy_check": "reasoning",
    "grounding_check": "reasoning",
    "response_review": "reasoning",
}
