"""app.workflow.runner.get_checkpointer's backend selection (spec: Phase
9.1a) - CHECKPOINT_BACKEND picks sqlite (default) or postgres, mirroring
VECTOR_BACKEND's own pattern. Patches the real saver classes' connection
entrypoints rather than opening a real Postgres connection - this test
is about selection logic, not the actual read/write/interrupt-resume
round trip (verified separately, live, against this project's real
Docker Postgres service - see the plan file's Phase 9.1 verification note).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.workflow.runner import _postgres_checkpoint_dsn, get_checkpointer


@pytest.fixture(autouse=True)
def _reset_checkpoint_backend():
    yield
    os.environ.pop("CHECKPOINT_BACKEND", None)
    get_settings.cache_clear()


def test_postgres_dsn_strips_asyncpg_driver_suffix():
    assert (
        _postgres_checkpoint_dsn("postgresql+asyncpg://support:support@postgres:5432/support")
        == "postgresql://support:support@postgres:5432/support"
    )


def test_postgres_dsn_strips_psycopg_driver_suffix():
    assert (
        _postgres_checkpoint_dsn("postgresql+psycopg://support:support@postgres:5432/support")
        == "postgresql://support:support@postgres:5432/support"
    )


def test_postgres_dsn_leaves_a_plain_dsn_unchanged():
    assert _postgres_checkpoint_dsn("postgresql://a:b@host/db") == "postgresql://a:b@host/db"


async def test_default_backend_uses_sqlite_saver(monkeypatch):
    os.environ.pop("CHECKPOINT_BACKEND", None)
    get_settings.cache_clear()
    saver_sentinel = object()

    @asynccontextmanager
    async def _fake_from_conn_string(_conn_string):
        yield saver_sentinel

    monkeypatch.setattr(
        "app.workflow.runner.AsyncSqliteSaver.from_conn_string", _fake_from_conn_string
    )

    async with get_checkpointer() as saver:
        assert saver is saver_sentinel


async def test_postgres_backend_uses_postgres_saver(monkeypatch):
    os.environ["CHECKPOINT_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://support:support@postgres:5432/support"
    get_settings.cache_clear()
    saver_sentinel = object()
    seen_dsn = {}

    @asynccontextmanager
    async def _fake_from_conn_string(conn_string):
        seen_dsn["dsn"] = conn_string
        yield saver_sentinel

    fake_module = AsyncMock()
    fake_module.AsyncPostgresSaver.from_conn_string = _fake_from_conn_string
    monkeypatch.setitem(
        __import__("sys").modules, "langgraph.checkpoint.postgres.aio", fake_module
    )

    async with get_checkpointer() as saver:
        assert saver is saver_sentinel
    # The +asyncpg suffix must never reach psycopg - it doesn't understand it.
    assert seen_dsn["dsn"] == "postgresql://support:support@postgres:5432/support"
