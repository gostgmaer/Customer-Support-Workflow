from __future__ import annotations

import builtins

from sqlalchemy import select

from app.domain.models import Integration
from app.repositories.base import TenantScopedRepository


class IntegrationRepository(TenantScopedRepository):
    async def list(self) -> list[Integration]:
        stmt = self._scope(select(Integration), Integration).order_by(Integration.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, integration_id: str) -> Integration | None:
        stmt = self._scope(select(Integration).where(Integration.id == integration_id), Integration)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Integration | None:
        stmt = self._scope(select(Integration).where(Integration.name == name), Integration)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_enabled_by_type(self, type_: str) -> Integration | None:
        """The first enabled integration of this type - used by automatic
        hooks (e.g. JIRA auto-create on escalation) where there is exactly
        one active connector per type per tenant in the common case."""
        stmt = self._scope(
            select(Integration).where(Integration.type == type_, Integration.enabled.is_(True)),
            Integration,
        ).order_by(Integration.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_enabled_by_type(self, type_: str) -> builtins.list[Integration]:
        """Every enabled integration of this type - unlike
        `get_enabled_by_type`, used where more than one active connector
        per type makes sense (MCP: a tenant may connect several servers,
        unlike the "exactly one JIRA/SMTP" assumption elsewhere).

        Return type is spelled `builtins.list[...]` rather than `list[...]`
        because this class already has a method named `list` - by the time
        mypy resolves this later method's annotation, the bare name `list`
        in class scope refers to that method, not the builtin."""
        stmt = self._scope(
            select(Integration).where(Integration.type == type_, Integration.enabled.is_(True)),
            Integration,
        ).order_by(Integration.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, integration: Integration) -> Integration:
        integration.tenant_id = self.tenant_id
        self.session.add(integration)
        await self.session.flush()
        return integration

    async def delete(self, integration: Integration) -> None:
        await self.session.delete(integration)
        await self.session.flush()
