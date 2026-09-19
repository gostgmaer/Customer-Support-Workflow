"""Full-text search column for real hybrid (vector + keyword) retrieval
(spec: Phase 11 RAG retrieval upgrade). A generated `tsvector` column
computed from `metadata->>'text'` (the chunk text, stamped there by
app.rag.ingest) with a GIN index lets `PgVectorStore.search_keyword` run a
real `ts_rank`/`plainto_tsquery` query instead of a Python-side scan -
this is what lets a document the (lossy) embedding step fails to surface
still be recovered by an exact keyword match, fused with vector results
via RRF in app.rag.retriever.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-19

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # See 0013 - the in-memory backend never touches this table.
        return

    op.execute(
        "ALTER TABLE vector_embeddings "
        "ADD COLUMN text_search tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', coalesce(metadata->>'text', ''))) STORED"
    )
    op.execute(
        "CREATE INDEX vector_embeddings_text_search_gin_idx ON vector_embeddings USING gin (text_search)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS vector_embeddings_text_search_gin_idx")
    op.execute("ALTER TABLE vector_embeddings DROP COLUMN IF EXISTS text_search")
