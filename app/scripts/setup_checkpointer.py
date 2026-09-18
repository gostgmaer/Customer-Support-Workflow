"""One-time LangGraph Postgres checkpointer schema init (spec: Phase 9.1a).

`AsyncPostgresSaver.setup()` must run exactly once before the app relies
on it - not on every `get_checkpointer()` call (a real per-request cost,
and a race under concurrent instances). Run this once at deploy time,
immediately after `alembic upgrade head` and before starting the app
(see docker-compose.yml's `api` command) - a no-op, exit 0, whenever
`CHECKPOINT_BACKEND` isn't `"postgres"`, so it's always safe to include
in the startup command regardless of backend.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.observability.logging import get_logger
from app.workflow.runner import _postgres_checkpoint_dsn

logger = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    if settings.checkpoint_backend != "postgres":
        logger.info("setup_checkpointer_skipped", checkpoint_backend=settings.checkpoint_backend)
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = _postgres_checkpoint_dsn(settings.database_url)
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
    logger.info("setup_checkpointer_done")


if __name__ == "__main__":
    asyncio.run(main())
