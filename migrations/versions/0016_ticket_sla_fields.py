"""support_tickets SLA fields (spec: Phase 15) - first_response_due_at/
resolution_due_at are computed once at ticket creation from the priority to
SLA-minutes mapping in app.config.policies, and first_responded_at/
resolved_at are stamped at the two real staff-action points in
app.workflow.runner.resume_workflow. No scheduler exists anywhere in this
codebase (a deliberate, repeated constraint - see RAG doc sync/webhook
correlation) - breach status is never computed by a background sweep, only
on-demand at read time by comparing now() against these columns. All
nullable: a ticket created before this migration has none, and every
consumer (API schema, frontend, analytics queries) already treats a null
due-at/resolved-at as "not tracked/not yet resolved" rather than assuming a
backfill.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-23

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "support_tickets", sa.Column("first_response_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "support_tickets", sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "support_tickets", sa.Column("first_responded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("support_tickets", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("support_tickets", "resolved_at")
    op.drop_column("support_tickets", "first_responded_at")
    op.drop_column("support_tickets", "resolution_due_at")
    op.drop_column("support_tickets", "first_response_due_at")
