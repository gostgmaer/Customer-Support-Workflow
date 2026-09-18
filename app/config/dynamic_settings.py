"""Per-tenant runtime setting overrides (spec §32/§43).

A deliberately small allow-list of *operational tunables* - never secrets -
can be overridden per tenant in the `system_settings` table instead of an
env var + redeploy: `OVERRIDABLE_SETTINGS` is both the schema and the
security boundary, since `validate_setting` rejects any key not in it (so a
caller can never use this path to set `JWT_SECRET`, `DATABASE_URL`, or an
API key - those stay env-only, see docs/SECURITY.md).

`get_effective_settings(session, tenant_id)` overlays this tenant's DB
overrides on top of the env-var defaults (`app.config.settings.Settings`),
cached in-process for `_CACHE_TTL_SECONDS` since it's on the hot path
(every LLM-calling node, every `/support/messages` request).
`invalidate_effective_settings_cache` is called by the admin settings API
after every write so the change is visible immediately on this instance;
the TTL is only a safety net for *other* API instances in a multi-instance
deployment that haven't seen the write yet - the same "process-local,
correct for one instance" caveat already documented for
`InMemoryRateLimiter` (see docs/SECURITY.md).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import ValidationError
from app.repositories.system_settings import SystemSettingRepository

KNOWN_LLM_PROVIDERS = {"google", "xai", "anthropic"}

# key -> validator. Only these keys can ever be written to system_settings
# (app.api.routes.admin_settings enforces this at the API boundary too).
OVERRIDABLE_SETTINGS = {
    "mock_llm",
    "default_llm_provider",
    "fallback_llm_provider",
    "confidence_intent",
    "confidence_retrieval",
    "rate_limit_per_window",
    "rate_limit_window_seconds",
    "llm_budget_usd_per_run",
    "escalation_max_failed_attempts",
}


@dataclass(frozen=True)
class EffectiveSettings:
    mock_llm: bool
    default_llm_provider: str
    fallback_llm_provider: str
    confidence_intent: float
    confidence_retrieval: float
    rate_limit_per_window: int
    rate_limit_window_seconds: int
    llm_budget_usd_per_run: float | None
    escalation_max_failed_attempts: int


def _base(settings: Settings) -> EffectiveSettings:
    return EffectiveSettings(
        mock_llm=settings.mock_llm,
        default_llm_provider=settings.default_llm_provider,
        fallback_llm_provider=settings.fallback_llm_provider,
        confidence_intent=settings.confidence_intent,
        confidence_retrieval=settings.confidence_retrieval,
        rate_limit_per_window=settings.rate_limit_per_window,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
        llm_budget_usd_per_run=settings.llm_budget_usd_per_run,
        escalation_max_failed_attempts=settings.escalation_max_failed_attempts,
    )


def validate_setting(key: str, value: object) -> None:
    """Raises ValidationError if `key` isn't overridable or `value` is the
    wrong shape for it. This is the single enforcement point for both the
    allow-list and the type/range checks - called from the admin API before
    anything is written."""
    if key not in OVERRIDABLE_SETTINGS:
        raise ValidationError(
            f"'{key}' is not an overridable setting. Allowed: {sorted(OVERRIDABLE_SETTINGS)}"
        )
    if key in ("default_llm_provider", "fallback_llm_provider"):
        if value not in KNOWN_LLM_PROVIDERS:
            raise ValidationError(f"'{key}' must be one of {sorted(KNOWN_LLM_PROVIDERS)}")
    elif key in ("confidence_intent", "confidence_retrieval"):
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0.0 <= float(value) <= 1.0:
            raise ValidationError(f"'{key}' must be a number between 0 and 1")
    elif key in ("rate_limit_per_window", "rate_limit_window_seconds", "escalation_max_failed_attempts"):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError(f"'{key}' must be a positive integer")
    elif key == "llm_budget_usd_per_run":
        if value is not None and (isinstance(value, bool) or not isinstance(value, int | float) or value < 0):
            raise ValidationError(f"'{key}' must be null or a non-negative number")
    elif key == "mock_llm" and not isinstance(value, bool):
        raise ValidationError(f"'{key}' must be a boolean")


# updated_by value written by seed_default_settings - distinguishes a
# never-touched key (would show "system" forever) from one an admin has
# actually changed (their real staff_id) in the GET /admin/settings response.
SEED_UPDATED_BY = "system"


async def seed_default_settings(session: AsyncSession, tenant_id: str) -> bool:
    """Writes one `system_settings` row per `OVERRIDABLE_SETTINGS` key for
    `tenant_id`, from whatever `app.config.get_settings()` currently
    resolves to (env vars / code defaults) - called once at app startup
    (see `app.main`'s `lifespan`) so the database, not `.env`, is this
    tenant's source of truth for these keys from the first run onward.

    A no-op (returns False) if this tenant already has *any*
    `system_settings` rows - this only ever runs once per tenant's
    lifetime; it never re-seeds a key an admin later deleted back to
    "default" on purpose.

    This is a deliberate tradeoff (spec §32/§43): once this has run,
    editing one of these keys in `.env` and restarting has **no effect**
    for this tenant until the corresponding row is changed/deleted via the
    admin API - see "DB-backed runtime settings" in docs/SECURITY.md.
    """
    repo = SystemSettingRepository(session, tenant_id)
    if await repo.list():
        return False
    settings = get_settings()
    for key in OVERRIDABLE_SETTINGS:
        await repo.upsert(key, json.dumps(getattr(settings, key)), updated_by=SEED_UPDATED_BY)
    await session.commit()
    invalidate_effective_settings_cache(tenant_id)
    return True


_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, EffectiveSettings]] = {}


async def get_effective_settings(session: AsyncSession, tenant_id: str) -> EffectiveSettings:
    cached = _cache.get(tenant_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    effective = _base(get_settings())
    overrides = await SystemSettingRepository(session, tenant_id).list()
    for row in overrides:
        if row.key not in OVERRIDABLE_SETTINGS:
            continue  # a key removed from the allow-list since it was set
        effective = replace(effective, **{row.key: json.loads(row.value)})

    _cache[tenant_id] = (now, effective)
    return effective


def invalidate_effective_settings_cache(tenant_id: str) -> None:
    _cache.pop(tenant_id, None)


def reset_effective_settings_cache() -> None:
    """Test-only: clears the whole cache (e.g. between tests sharing a tenant id)."""
    _cache.clear()
