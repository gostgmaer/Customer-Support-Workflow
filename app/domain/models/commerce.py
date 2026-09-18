"""Backing commerce data for customer-data tools (orders/payments/subscriptions).

Not explicitly named as tables in spec §27's list, but required so
app.tools.* have real data to query instead of hard-coded fixtures baked
into tool code.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UTCDateTime, new_uuid


class Order(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))  # placed|shipped|in_transit|delivered|cancelled
    total_amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    product_name: Mapped[str] = mapped_column(String(200))
    carrier: Mapped[str] = mapped_column(String(50), default="")
    tracking_number: Mapped[str] = mapped_column(String(50), default="")
    estimated_delivery: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    placed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Payment(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))  # succeeded|failed|pending|refunded
    amount: Mapped[float] = mapped_column(Float)
    failure_reason: Mapped[str] = mapped_column(String(200), default="")
    # spec: Phase 9.4b - set only when a real gateway (e.g. "stripe") is
    # involved; both None for the pure-DB-simulation path this app used
    # exclusively before this phase (and still uses when no gateway
    # integration is configured for the tenant).
    gateway: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gateway_payment_intent_id: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Subscription(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    plan: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30))  # active|cancelled|past_due
    renews_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RefundRequest(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "refund_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    order_id: Mapped[str] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("customers.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending|approved|rejected|completed
    reason: Mapped[str] = mapped_column(String(500), default="")
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True, unique=True)
    # spec: Phase 9.4b - set only when a real gateway refund was issued
    # (app.workflow.nodes.human_approval's refund-approval branch, when a
    # "stripe" integration is configured and the order's Payment has a
    # gateway_payment_intent_id). Both None for the pure-DB-simulation path.
    gateway: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gateway_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
