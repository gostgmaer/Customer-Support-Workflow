"""vector embeddings table (pgvector-backend storage)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vector_embeddings",
        sa.Column("namespace", sa.String(100), primary_key=True),
        sa.Column("chunk_id", sa.String(36), primary_key=True),
        sa.Column("embedding", sa.JSON, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("vector_embeddings")
