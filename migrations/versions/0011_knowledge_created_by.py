"""knowledge_documents.created_by - the staff id that uploaded a document
via POST /api/v1/knowledge/upload (spec: help-desk-kit-style KB upload
metadata). Nullable - a `make seed`/docs-integration-synced document has
no human uploader to attribute, mirroring integrations.created_by's
precedent for anything that predates this column.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-19

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("created_by", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_documents", "created_by")
