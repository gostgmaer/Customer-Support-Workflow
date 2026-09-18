"""Provider health tracking (spec §8): HEALTHY / DEGRADED / DISABLED per
provider, updated from call outcomes. The router (`app.llm.router`) skips
DISABLED providers rather than sending them traffic. Process-local (like
the in-memory vector store / rate limiter) - fine for a single instance;
share via Redis if you need this coordinated across API instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
DISABLED = "DISABLED"

# After this many consecutive failures a provider is marked DEGRADED; at
# double that, DISABLED. Recovers to HEALTHY on the next success.
_DEGRADE_AFTER = 3
_DISABLE_AFTER = 6


@dataclass
class _ProviderHealthState:
    consecutive_failures: int = 0
    status: str = HEALTHY


@dataclass
class ProviderHealthRegistry:
    _states: dict[str, _ProviderHealthState] = field(default_factory=dict)

    def reset(self) -> None:
        self._states.clear()

    def _state(self, provider: str) -> _ProviderHealthState:
        return self._states.setdefault(provider, _ProviderHealthState())

    def record_success(self, provider: str) -> None:
        state = self._state(provider)
        state.consecutive_failures = 0
        state.status = HEALTHY

    def record_failure(self, provider: str) -> None:
        state = self._state(provider)
        state.consecutive_failures += 1
        if state.consecutive_failures >= _DISABLE_AFTER:
            state.status = DISABLED
        elif state.consecutive_failures >= _DEGRADE_AFTER:
            state.status = DEGRADED

    def status(self, provider: str) -> str:
        return self._state(provider).status

    def is_disabled(self, provider: str) -> bool:
        return self.status(provider) == DISABLED

    def snapshot(self) -> dict[str, str]:
        return {name: state.status for name, state in self._states.items()}


_registry = ProviderHealthRegistry()


def get_health_registry() -> ProviderHealthRegistry:
    return _registry
