"""payments.gateway/gateway_payment_intent_id and
refund_requests.gateway/gateway_reference (spec: Phase 9.4b) - links a
Payment/RefundRequest row to a real external payment processor (Stripe).
Nullable, no backfill needed - existing rows simply have no gateway.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-17

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("gateway", sa.String(30), nullable=True))
    op.add_column("payments", sa.Column("gateway_payment_intent_id", sa.String(200), nullable=True))
    op.add_column("refund_requests", sa.Column("gateway", sa.String(30), nullable=True))
    op.add_column("refund_requests", sa.Column("gateway_reference", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("refund_requests", "gateway_reference")
    op.drop_column("refund_requests", "gateway")
    op.drop_column("payments", "gateway_payment_intent_id")
    op.drop_column("payments", "gateway")
