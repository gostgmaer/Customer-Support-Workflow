"""Provider-agnostic LLM abstraction (spec §3-4).

The application requests a model **by purpose** (`app.llm.router.get_llm_router().get_model(purpose)`),
never by provider - nothing outside `app/llm/` should import a specific
provider adapter or a vendor SDK. Every provider adapter implements this
same Protocol so the workflow/agents code is identical regardless of which
vendor is actually serving the request.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class TokenUsage:
    """Reported to an optional `usage_callback` after each call (spec §42:
    cost tracking). Never raises/propagates from the callback boundary -
    see app.workflow.graph._traced's RecordingLLMRouter, the only current
    caller that supplies one."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


UsageCallback = Callable[[TokenUsage], None | Awaitable[None]]


class LLMProvider(Protocol):
    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> str:
        """Free-form text generation."""
        ...

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema: type[T],
        max_tokens: int = 1024,
        usage_callback: UsageCallback | None = None,
    ) -> T:
        """Generation constrained to a Pydantic schema."""
        ...
