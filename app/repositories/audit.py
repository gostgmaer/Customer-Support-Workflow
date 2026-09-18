from __future__ import annotations

from app.domain.models import AuditLog
from app.repositories.base import TenantScopedRepository


class AuditRepository(TenantScopedRepository):
    async def record(
        self,
        *,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        correlation_id: str,
        details: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            tenant_id=self.tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            correlation_id=correlation_id,
            details=details or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
