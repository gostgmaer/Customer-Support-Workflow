"""support_tickets.pending_call/execution_result (spec: Phase 8.2) - the
proposed external-tool-call details and its post-approval result,
previously visible only as flattened text in summary/actions_taken.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-12

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("support_tickets", sa.Column("pending_call", sa.JSON(), nullable=True))
    op.add_column("support_tickets", sa.Column("execution_result", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("support_tickets", "execution_result")
    op.drop_column("support_tickets", "pending_call")
