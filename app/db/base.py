from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# The zero-setup single-tenant path needs no configuration: every row
# belongs to this tenant unless a real multi-tenant deployment issues JWTs
# with a different `tenant_id` claim (spec §43).
DEFAULT_TENANT_ID = "default"


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """`DateTime(timezone=True)`, but actually round-trips as UTC on every
    backend. Every value written here is already UTC (see `utcnow()`
    above), but SQLite has no native timezone-aware datetime type - it
    silently drops tzinfo on write and hands back a *naive* datetime on
    read, which every `datetime`-typed field in every API response schema
    (spec §26) then serializes with no timezone suffix at all (e.g.
    `"2026-09-09T08:23:47.788417"`). A consumer doing `new Date(...)` on
    that - the frontend included - parses it as *local* time instead of
    UTC, silently shifting every displayed timestamp by the reader's UTC
    offset. Postgres preserves tzinfo natively, so this is a no-op there;
    for SQLite it re-attaches UTC on the way out."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return value


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TenantScopedMixin:
    """Every relevant entity carries a tenant_id (spec §43); tenant data
    must never leak across tenants. See app.repositories.base.TenantScopedRepository
    for the query-scoping side of this."""

    tenant_id: Mapped[str] = mapped_column(String(100), default=DEFAULT_TENANT_ID, index=True)
