"""knowledge_documents.view_count/helpful_yes_count/helpful_no_count -
engagement counters for the staff-facing Knowledge Base browse UI
(popular articles, "was this helpful"). Not touched by ingestion; all
default to 0 for existing rows.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-18

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("helpful_yes_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("helpful_no_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("knowledge_documents", "helpful_no_count")
    op.drop_column("knowledge_documents", "helpful_yes_count")
    op.drop_column("knowledge_documents", "view_count")
