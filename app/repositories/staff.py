from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import StaffUser


class StaffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> StaffUser | None:
        result = await self._session.execute(select(StaffUser).where(StaffUser.username == username))
        return result.scalar_one_or_none()

    async def create(self, staff: StaffUser) -> StaffUser:
        self._session.add(staff)
        await self._session.flush()
        return staff

    async def list_by_tenant(self, tenant_id: str) -> list[StaffUser]:
        result = await self._session.execute(
            select(StaffUser).where(StaffUser.tenant_id == tenant_id).order_by(StaffUser.username)
        )
        return list(result.scalars().all())
