"""knowledge_documents.storage_provider/storage_key - records where the
*original* uploaded file (not just its extracted raw_text) lives, if it
was stored at all (spec: multi-provider KB upload storage, R2 default,
see app.storage.*). Both nullable: storing the original file is optional
(never blocks a KB upload if the configured provider is unreachable/
unconfigured), and a document ingested via `make seed` or a
docs-integration sync never had an original file to store in the first
place.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-19

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_documents", sa.Column("storage_provider", sa.String(20), nullable=True))
    op.add_column("knowledge_documents", sa.Column("storage_key", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_documents", "storage_key")
    op.drop_column("knowledge_documents", "storage_provider")
