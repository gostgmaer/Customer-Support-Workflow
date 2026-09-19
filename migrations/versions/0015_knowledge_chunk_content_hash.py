"""knowledge_chunks.content_hash - lets ingest-time dedup (spec: Phase 11
Tier 2.3) skip re-embedding a chunk whose text hasn't changed between
syncs, instead of wiping and rebuilding every chunk of a document on
every version bump (see app.rag.ingest). Nullable: existing rows
predating this column have none, and app.rag.ingest's diff logic already
treats a null/unmatched hash as "not present, must be replaced" rather
than assuming every legacy row needs a backfill.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-19

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_chunks", sa.Column("content_hash", sa.String(32), nullable=True))
    op.create_index("ix_knowledge_chunks_content_hash", "knowledge_chunks", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "content_hash")
