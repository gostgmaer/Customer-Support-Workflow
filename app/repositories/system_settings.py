from __future__ import annotations

from sqlalchemy import select

from app.domain.models import SystemSetting
from app.repositories.base import TenantScopedRepository


class SystemSettingRepository(TenantScopedRepository):
    async def list(self) -> list[SystemSetting]:
        stmt = self._scope(select(SystemSetting), SystemSetting)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, key: str) -> SystemSetting | None:
        stmt = self._scope(select(SystemSetting).where(SystemSetting.key == key), SystemSetting)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, key: str, value_json: str, *, updated_by: str) -> SystemSetting:
        existing = await self.get(key)
        if existing is not None:
            existing.value = value_json
            existing.updated_by = updated_by
            await self.session.flush()
            return existing
        row = SystemSetting(tenant_id=self.tenant_id, key=key, value=value_json, updated_by=updated_by)
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, key: str) -> None:
        existing = await self.get(key)
        if existing is not None:
            await self.session.delete(existing)
            await self.session.flush()
