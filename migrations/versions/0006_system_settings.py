"""system_settings: DB-backed per-tenant runtime setting overrides (spec §32/§43)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-09

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "key", name="uq_system_settings_tenant_key"),
    )
    op.create_index("ix_system_settings_tenant_id", "system_settings", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_system_settings_tenant_id", table_name="system_settings")
    op.drop_table("system_settings")
