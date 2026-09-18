"""multi-tenancy: tenant_id on every domain table (spec §43)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_TENANT_ID = "default"

TABLES = [
    "customers",
    "orders",
    "payments",
    "subscriptions",
    "refund_requests",
    "conversations",
    "messages",
    "workflow_runs",
    "workflow_events",
    "support_tickets",
    "tool_executions",
    "knowledge_documents",
    "knowledge_chunks",
    "staff_users",
    "feedback",
    "audit_logs",
    "idempotency_keys",
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(100), nullable=False, server_default=DEFAULT_TENANT_ID),
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
