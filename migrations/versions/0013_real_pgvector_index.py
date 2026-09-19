"""Real pgvector storage + HNSW index for vector_embeddings (spec: Phase 11
RAG retrieval upgrade). `PgVectorStore` previously stored embeddings as a
plain JSON array and scored every row in the namespace in Python (no
LIMIT, no index) - this adds a real `vector` column plus an HNSW index so
`ORDER BY embedding_vec <=> :query LIMIT :top_k` can do the work in
Postgres. The old `embedding` JSON column is left in place (not dropped
or backfilled here) as a rollback path - drop it in a later, separate
migration once the cutover is confirmed safe. `metadata` is widened from
`json` to `jsonb` so it supports the `@>` containment operator (used for
metadata-filtered search) and, in migration 0014, a GIN-indexed full-text
column - `json` supports neither.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-19

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite has no pgvector extension/HNSW index - the in-memory
        # vector store (VECTOR_BACKEND=memory, the sqlite-mode default)
        # never touches this table, so there is nothing to migrate.
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE vector_embeddings ALTER COLUMN metadata TYPE jsonb USING metadata::jsonb")
    op.execute("ALTER TABLE vector_embeddings ADD COLUMN embedding_vec vector(768)")
    op.execute(
        "CREATE INDEX vector_embeddings_embedding_vec_hnsw_idx "
        "ON vector_embeddings USING hnsw (embedding_vec vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS vector_embeddings_embedding_vec_hnsw_idx")
    op.execute("ALTER TABLE vector_embeddings DROP COLUMN IF EXISTS embedding_vec")
    op.execute("ALTER TABLE vector_embeddings ALTER COLUMN metadata TYPE json USING metadata::json")
