from __future__ import annotations

from sqlalchemy import select

from app.domain.models import Order, Payment, RefundRequest, Subscription
from app.repositories.base import TenantScopedRepository


class OrderRepository(TenantScopedRepository):
    async def get(self, order_id: str) -> Order | None:
        stmt = self._scope(select(Order).where(Order.id == order_id), Order)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_customer(self, customer_id: str, *, limit: int = 20) -> list[Order]:
        stmt = self._scope(
            select(Order).where(Order.customer_id == customer_id).order_by(Order.placed_at.desc()),
            Order,
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, order: Order, status: str) -> Order:
        order.status = status
        await self.session.flush()
        return order


class PaymentRepository(TenantScopedRepository):
    async def get_latest_for_order(self, order_id: str) -> Payment | None:
        stmt = self._scope(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc()),
            Payment,
        ).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_gateway_payment_intent_id(self, payment_intent_id: str) -> Payment | None:
        """spec: Phase 9.4b - how the Stripe webhook route
        (app.api.routes.webhooks) finds which Payment row a
        `payment_intent.succeeded`/`payment_intent.payment_failed` event
        is about."""
        stmt = self._scope(
            select(Payment).where(Payment.gateway_payment_intent_id == payment_intent_id), Payment
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, payment: Payment, status: str) -> Payment:
        payment.status = status
        await self.session.flush()
        return payment


class SubscriptionRepository(TenantScopedRepository):
    async def get_active_for_customer(self, customer_id: str) -> Subscription | None:
        stmt = self._scope(
            select(Subscription)
            .where(Subscription.customer_id == customer_id)
            .order_by(Subscription.created_at.desc()),
            Subscription,
        ).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(self, subscription: Subscription, status: str) -> Subscription:
        subscription.status = status
        await self.session.flush()
        return subscription

    async def update_plan(self, subscription: Subscription, plan: str) -> Subscription:
        subscription.plan = plan
        await self.session.flush()
        return subscription


class RefundRepository(TenantScopedRepository):
    async def get(self, refund_id: str) -> RefundRequest | None:
        stmt = self._scope(select(RefundRequest).where(RefundRequest.id == refund_id), RefundRequest)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, key: str) -> RefundRequest | None:
        stmt = self._scope(select(RefundRequest).where(RefundRequest.idempotency_key == key), RefundRequest)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_gateway_reference(self, reference: str) -> RefundRequest | None:
        """spec: Phase 9.4b - how the Stripe webhook route
        (app.api.routes.webhooks) finds which RefundRequest row a
        `refund.updated` event is about."""
        stmt = self._scope(
            select(RefundRequest).where(RefundRequest.gateway_reference == reference), RefundRequest
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, refund: RefundRequest) -> RefundRequest:
        refund.tenant_id = self.tenant_id
        self.session.add(refund)
        await self.session.flush()
        return refund

    async def update_status(self, refund: RefundRequest, status: str) -> RefundRequest:
        refund.status = status
        await self.session.flush()
        return refund

    async def get_for_order(self, order_id: str) -> RefundRequest | None:
        stmt = self._scope(
            select(RefundRequest)
            .where(RefundRequest.order_id == order_id)
            .order_by(RefundRequest.created_at.desc()),
            RefundRequest,
        ).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
