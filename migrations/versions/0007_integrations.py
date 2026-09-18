"""integrations: external system connections (JIRA/WooCommerce/SMTP/custom)
plus support_tickets.external_ref/external_url for auto-created JIRA issues

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-09

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("auth_type", sa.String(20), nullable=False),
        sa.Column("encrypted_credentials", sa.String(2000), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_integrations_tenant_name"),
    )
    op.create_index("ix_integrations_tenant_id", "integrations", ["tenant_id"])

    op.add_column("support_tickets", sa.Column("external_ref", sa.String(100), nullable=True))
    op.add_column("support_tickets", sa.Column("external_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("support_tickets", "external_url")
    op.drop_column("support_tickets", "external_ref")
    op.drop_index("ix_integrations_tenant_id", table_name="integrations")
    op.drop_table("integrations")
