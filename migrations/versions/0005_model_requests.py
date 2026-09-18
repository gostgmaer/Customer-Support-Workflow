"""model_requests: LLM cost/token tracking (spec §42)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False, server_default="default"),
        sa.Column("workflow_run_id", sa.String(36), nullable=True),
        sa.Column("node_name", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_requests_tenant_id", "model_requests", ["tenant_id"])
    op.create_index("ix_model_requests_workflow_run_id", "model_requests", ["workflow_run_id"])


def downgrade() -> None:
    op.drop_index("ix_model_requests_workflow_run_id", table_name="model_requests")
    op.drop_index("ix_model_requests_tenant_id", table_name="model_requests")
    op.drop_table("model_requests")
