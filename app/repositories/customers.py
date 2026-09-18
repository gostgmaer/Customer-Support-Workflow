from __future__ import annotations

from sqlalchemy import select

from app.domain.models import Customer
from app.repositories.base import TenantScopedRepository


class CustomerRepository(TenantScopedRepository):
    async def get(self, customer_id: str) -> Customer | None:
        stmt = self._scope(select(Customer).where(Customer.id == customer_id), Customer)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Customer | None:
        stmt = self._scope(select(Customer).where(Customer.email == email), Customer)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, customer: Customer) -> Customer:
        customer.tenant_id = self.tenant_id
        self.session.add(customer)
        await self.session.flush()
        return customer
