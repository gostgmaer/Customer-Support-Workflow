"""Approximate model pricing for cost estimation (spec §42).

$ per 1,000,000 tokens, (input, output). Pricing changes frequently and
varies by region/volume tier - treat these as reasonable defaults for
relative cost tracking and budget enforcement, not billing-accurate
figures. Update as needed; an unknown model logs a warning and costs $0
rather than raising, so an unpriced model never breaks the workflow.
"""

from __future__ import annotations

from app.observability.logging import get_logger

logger = get_logger(__name__)

# (input $/1M tokens, output $/1M tokens)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "grok-4-fast": (0.20, 0.50),
    "grok-4": (3.00, 15.00),
    "claude-sonnet-5": (3.00, 15.00),
}


def estimate_cost_usd(model: str, *, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        logger.warning("model_pricing_unknown", model=model)
        return 0.0
    input_price, output_price = pricing
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
