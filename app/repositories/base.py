"""Tenant-scoped repository base (spec §43: tenant data must never leak
across tenants). Every repository that touches a `TenantScopedMixin` table
extends this and calls `self._scope(stmt)` on every SELECT - the same
mechanical pattern repeated per repository, kept in one place here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession


class TenantScopedRepository:
    def __init__(self, session: AsyncSession, tenant_id: str) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def _scope(self, stmt: Select[Any], model: Any) -> Select[Any]:
        return stmt.where(model.tenant_id == self.tenant_id)
