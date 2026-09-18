from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin, TimestampMixin, UTCDateTime, new_uuid


class KnowledgeDocument(Base, TimestampMixin, TenantScopedMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    effective_date: Mapped[datetime] = mapped_column(UTCDateTime)
    expiration_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    raw_text: Mapped[str] = mapped_column(Text)


class KnowledgeChunk(Base, TimestampMixin, TenantScopedMixin):
    """Chunk metadata/text. Embeddings live in the vector-store backend
    (in-memory or pgvector), keyed by this chunk's `id` - see
    app.repositories.vector_store.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id"), index=True
    )
    chunk_index: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
