from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
        _engine = create_async_engine(settings.database_url, echo=False, connect_args=connect_args)
        if settings.is_sqlite:
            # SQLite does not enforce FOREIGN KEY constraints by default -
            # a raw ForeignKey column (no ORM relationship()) with a wrong
            # flush order silently succeeds here and only fails against a
            # real constraint-enforcing database (Postgres) in production.
            # Enforcing it in dev/test too means the whole test suite - not
            # just Postgres deployments - catches this class of bug (see
            # the app.rag.ingest fix this discovered: KnowledgeChunk rows
            # could flush before their parent KnowledgeDocument).
            @event.listens_for(_engine.sync_engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        yield session


async def init_models() -> None:
    """Create tables directly for local/dev/test sqlite runs.

    Production deployments use Alembic migrations (see migrations/) instead
    of this - it is only invoked for the zero-setup sqlite path.
    """
    from app.db.base import Base
    from app.domain import models  # noqa: F401  (registers ORM models on Base.metadata)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
