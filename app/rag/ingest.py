"""Ingestion pipeline (spec §8): Documents -> Loader -> Cleaning -> Chunking
-> Metadata enrichment -> Embeddings -> Vector database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import DEFAULT_TENANT_ID, new_uuid
from app.domain.models import KnowledgeChunk, KnowledgeDocument
from app.observability.logging import get_logger
from app.rag.chunking import build_chunks
from app.rag.embeddings import Embedder, get_embedder
from app.rag.loaders import LoadedDocument, load_knowledge_directory
from app.repositories.vector_store import VectorRepository, get_vector_store

logger = get_logger(__name__)


def knowledge_namespace(tenant_id: str) -> str:
    """Vector-store namespace for a tenant's knowledge base (spec §43:
    "Vector retrieval must support tenant isolation") - two tenants'
    documents never share a namespace, so a search can never cross-match."""
    return f"knowledge:{tenant_id}"


async def ingest_documents(
    documents: list[LoadedDocument],
    session: AsyncSession,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    embedder: Embedder | None = None,
    vector_store: VectorRepository | None = None,
    update_on_version_change: bool = False,
) -> int:
    """Chunks+embeds `documents` and stores both the DB rows (source of
    truth) and the vector-store entries (search index) - the shared core
    of both `ingest_knowledge_directory` (local markdown files) and
    `app.rag.docs_ingest.sync_docs_integration` (spec: Phase 9.3 -
    external Confluence/Notion pages), extracted here so both reuse the
    exact same dedupe/flush/chunk/embed/upsert pipeline rather than
    duplicating it.

    Idempotent by `(tenant_id, title, source)`. `update_on_version_change=False`
    (the default, used for local files) skips a document that already
    exists, full stop - local markdown files are deliberately
    hand-versioned, so re-ingesting the same file is a deliberate no-op.
    `update_on_version_change=True` (used for external doc sources, which
    can change silently between syncs) instead re-ingests when the
    fetched document's `version` differs from what's stored: old chunks
    are deleted (DB row + vector-store entry) and replaced, rather than
    silently skipped or duplicated.
    """
    embedder = embedder or get_embedder()
    vector_store = vector_store or get_vector_store(session)

    chunk_count = 0
    for doc in documents:
        result = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.title == doc.title,
                KnowledgeDocument.source == doc.source,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None and not (update_on_version_change and existing.version != doc.version):
            continue

        old_chunks: list[KnowledgeChunk] = []
        if existing is not None:
            # Version changed since the last sync - diff chunks by
            # content_hash (spec: Phase 11 Tier 2.3) rather than always
            # wiping and rebuilding every chunk: a chunk whose text is
            # unchanged is left alone (no re-embed), only chunks whose
            # hash no longer appears in the fresh set are deleted below,
            # after the new chunk set is known.
            old_chunks_result = await session.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == existing.id)
            )
            old_chunks = list(old_chunks_result.scalars().all())
            existing.version = doc.version
            existing.raw_text = doc.text
            existing.effective_date = doc.effective_date
            existing.expiration_date = doc.expiration_date
            document_id = existing.id
        else:
            document_id = new_uuid()
            session.add(
                KnowledgeDocument(
                    id=document_id,
                    tenant_id=tenant_id,
                    title=doc.title,
                    source=doc.source,
                    category=doc.category,
                    version=doc.version,
                    effective_date=doc.effective_date,
                    expiration_date=doc.expiration_date,
                    language=doc.language,
                    raw_text=doc.text,
                )
            )
        # KnowledgeChunk.document_id is a bare ForeignKey column, not an ORM
        # relationship() - without one, SQLAlchemy's unit-of-work has no
        # cross-mapper dependency to sort by, so it doesn't guarantee this
        # document's INSERT happens before its chunks' at the eventual
        # commit. SQLite doesn't enforce the FK by default so this went
        # unnoticed; Postgres does. Flushing here makes the parent row
        # exist before any chunk referencing it is queued, regardless of
        # what order the rest of the session flushes in.
        await session.flush()
        chunks = build_chunks(doc, document_id=document_id)
        new_hashes = {chunk.metadata["content_hash"] for chunk in chunks}

        # A null/legacy hash is never in new_hashes, so a pre-Tier-2.3 row
        # is always treated as "not present, must be replaced" rather than
        # assumed unchanged - see the column's own migration note.
        retained_hashes: set[str] = set()
        for old_chunk in old_chunks:
            content_hash = old_chunk.content_hash
            if content_hash is not None and content_hash in new_hashes:
                retained_hashes.add(content_hash)
            else:
                await vector_store.delete(namespace=knowledge_namespace(tenant_id), chunk_id=old_chunk.id)
                await session.delete(old_chunk)
        if old_chunks:
            await session.flush()

        chunks_to_embed = [c for c in chunks if c.metadata["content_hash"] not in retained_hashes]
        if retained_hashes:
            logger.info(
                "ingest_dedup_skipped_unchanged_chunks",
                document_id=document_id,
                skipped=len(chunks) - len(chunks_to_embed),
                total=len(chunks),
            )

        embeddings = await embedder.embed_batch([c.text for c in chunks_to_embed])
        for chunk, embedding in zip(chunks_to_embed, embeddings, strict=True):
            chunk_id = new_uuid()
            session.add(
                KnowledgeChunk(
                    id=chunk_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    content_hash=chunk.metadata["content_hash"],
                    metadata_json=chunk.metadata,
                )
            )
            await vector_store.upsert(
                namespace=knowledge_namespace(tenant_id),
                chunk_id=chunk_id,
                embedding=embedding,
                metadata={
                    **chunk.metadata,
                    "text": chunk.text,
                    "chunk_id": chunk_id,
                    "embedding_model": embedder.model,
                    "embedding_version": embedder.embedding_version,
                },
            )
            chunk_count += 1
    await session.commit()
    return chunk_count


async def ingest_knowledge_directory(
    directory: Path,
    session: AsyncSession,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    embedder: Embedder | None = None,
    vector_store: VectorRepository | None = None,
) -> int:
    """Loads every document in `directory` and ingests it via
    `ingest_documents` - see that function for the dedupe/chunk/embed/
    upsert pipeline itself.
    """
    documents = load_knowledge_directory(directory)
    return await ingest_documents(
        documents, session, tenant_id=tenant_id, embedder=embedder, vector_store=vector_store
    )


async def warm_vector_index_from_db(
    session: AsyncSession,
    *,
    embedder: Embedder | None = None,
    vector_store: VectorRepository | None = None,
) -> int:
    """Rebuilds the vector-store search index from the durable
    knowledge_documents/knowledge_chunks tables, without writing to the DB -
    for every tenant present in the DB, each into its own namespace.

    Needed because the default `VECTOR_BACKEND=memory` store is process-
    local: it does not survive a process restart the way the DB does, so a
    fresh API process must re-embed the already-ingested chunks into its
    own in-memory index before it can answer any RAG query. Call this from
    app startup (see app.main lifespan) - it is a no-op for VECTOR_BACKEND
    =pgvector, where embeddings are already durably stored.
    """
    embedder = embedder or get_embedder()
    vector_store = vector_store or get_vector_store(session)

    rows = await session.execute(
        select(KnowledgeChunk, KnowledgeDocument).join(
            KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id
        )
    )
    chunks = rows.all()
    if not chunks:
        return 0

    embeddings = await embedder.embed_batch([chunk.text for chunk, _ in chunks])
    for (chunk, document), embedding in zip(chunks, embeddings, strict=True):
        metadata = {
            **chunk.metadata_json,
            "document_id": document.id,
            "title": document.title,
            "source": document.source,
            "category": document.category,
            "effective_date": document.effective_date.isoformat(),
            "expiration_date": document.expiration_date.isoformat() if document.expiration_date else None,
            "text": chunk.text,
            "chunk_id": chunk.id,
            "embedding_model": embedder.model,
            "embedding_version": embedder.embedding_version,
        }
        await vector_store.upsert(
            namespace=knowledge_namespace(chunk.tenant_id),
            chunk_id=chunk.id,
            embedding=embedding,
            metadata=metadata,
        )
    return len(chunks)
