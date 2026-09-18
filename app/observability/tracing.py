"""LangSmith integration (spec §13-15).

LangChain/LangGraph auto-trace every run once the standard `LANGSMITH_*` /
`LANGCHAIN_*` environment variables are set - there is no per-call
instrumentation code needed beyond that and attaching run metadata (spec
§13's `conversation_id`/`customer_tier`/`channel`/`environment` example),
which `build_run_metadata` below produces for `app.workflow.runner` to pass
into `graph.ainvoke(..., config={"metadata": ..., "tags": ...})`.

A no-op (LangSmith stays disabled) unless both `LANGSMITH_TRACING=true` and
`LANGSMITH_API_KEY` are set - tracing is opt-in, and PII must never be sent
unnecessarily (spec §13: "Do not send sensitive PII unnecessarily"), so
only the customer_id **hash** is included, never the raw id or message
text.
"""

from __future__ import annotations

import os

from app.config import Settings
from app.observability.logging import get_logger, hash_customer_id

logger = get_logger(__name__)


def configure_langsmith(settings: Settings) -> None:
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return
    # LangChain/LangGraph read these directly from the process environment.
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"  # older LangChain versions
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    logger.info("langsmith_tracing_enabled", project=settings.langsmith_project)


def build_run_metadata(
    *,
    conversation_id: str,
    customer_id: str,
    channel: str,
    environment: str,
    customer_tier: str | None = None,
) -> dict:
    """Per-run metadata attached to the LangGraph invocation (spec §13-14).
    Never includes the raw customer_id or any message content."""
    metadata: dict = {
        "conversation_id": conversation_id,
        "customer_id_hash": hash_customer_id(customer_id),
        "channel": channel,
        "environment": environment,
    }
    if customer_tier:
        metadata["customer_tier"] = customer_tier
    return metadata


def build_run_tags(*, channel: str, environment: str) -> list[str]:
    return ["customer-support", channel, environment]
