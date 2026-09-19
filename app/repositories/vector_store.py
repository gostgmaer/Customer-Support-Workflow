"""Vector store abstraction (spec §28).

`VectorRepository` is the interface the RAG retriever depends on. Two
implementations are provided, selected by `VECTOR_BACKEND`:

- `InMemoryVectorStore` (default): numpy cosine similarity, process-local.
  Zero setup, fine for the curated seed corpus and for tests.
- `PgVectorStore`: real pgvector-backed storage (spec: Phase 11 RAG
  retrieval upgrade) - a genuine `vector` column with an HNSW index
  (`ORDER BY embedding_vec <=> :query LIMIT :top_k`, see migration 0013),
  not the brute-force Python-side cosine scan this class used before.
  Also supports `search_keyword` (full-text search via a generated
  `tsvector` column + GIN index, migration 0014) for hybrid retrieval -
  see app.rag.retriever's RRF fusion of the two.

Both implementations support metadata filtering, namespace isolation,
upsert, and delete, per spec. `search_keyword` on `InMemoryVectorStore`
reuses `app.rag.reranker.lexical_overlap` as an equivalent in-process
scorer, since that backend's linear scan is already its documented
design for a small corpus.

Postgres-only behavior in this module (the real `vector`/`tsvector`
columns) has no automated pytest coverage, matching this codebase's own
established precedent for anything that needs a real Postgres instance
(see app.workflow.runner's checkpointer backend selection / Phase 9.1) -
the entire test suite runs against SQLite via `InMemoryVectorStore`
only; `PgVectorStore`'s real-Postgres behavior is verified manually
against the docker-compose Postgres service.
"""

from __future__ import annotations

import json
from typing import Protocol

import numpy as np
from pgvector import Vector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Deferred import (see InMemoryVectorStore.search_keyword) - app.rag.reranker
# imports VectorMatch from this module, so a top-level import here would be
# circular.


class VectorMatch:
    def __init__(self, chunk_id: str, score: float, metadata: dict) -> None:
        self.chunk_id = chunk_id
        self.score = score
        self.metadata = metadata


class VectorRepository(Protocol):
    async def upsert(
        self, *, namespace: str, chunk_id: str, embedding: list[float], metadata: dict
    ) -> None: ...

    async def delete(self, *, namespace: str, chunk_id: str) -> None: ...

    async def search(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[VectorMatch]: ...

    async def search_keyword(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[VectorMatch]: ...


def _matches_filter(metadata: dict, metadata_filter: dict | None) -> bool:
    if not metadata_filter:
        return True
    return all(metadata.get(k) == v for k, v in metadata_filter.items())


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-9
    return float(np.dot(a, b) / denom)


class InMemoryVectorStore:
    """Process-wide store (class-level dict, shared across instances) so
    data ingested via one request/session remains visible to the next -
    that is the point of the in-memory backend. Tests must call `.reset()`
    between cases to avoid cross-test pollution."""

    _store: dict[str, dict[str, tuple[np.ndarray, dict]]] = {}

    @classmethod
    def reset(cls) -> None:
        cls._store.clear()

    async def upsert(
        self, *, namespace: str, chunk_id: str, embedding: list[float], metadata: dict
    ) -> None:
        self._store.setdefault(namespace, {})[chunk_id] = (np.array(embedding, dtype=float), metadata)

    async def delete(self, *, namespace: str, chunk_id: str) -> None:
        self._store.get(namespace, {}).pop(chunk_id, None)

    async def search(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[VectorMatch]:
        query = np.array(query_embedding, dtype=float)
        candidates = self._store.get(namespace, {})
        scored = [
            VectorMatch(chunk_id, _cosine(query, vec), meta)
            for chunk_id, (vec, meta) in candidates.items()
            if _matches_filter(meta, metadata_filter)
        ]
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]

    async def search_keyword(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[VectorMatch]:
        from app.rag.reranker import lexical_overlap

        candidates = self._store.get(namespace, {})
        scored = [
            VectorMatch(chunk_id, lexical_overlap(query, meta.get("text", "")), meta)
            for chunk_id, (_vec, meta) in candidates.items()
            if _matches_filter(meta, metadata_filter)
        ]
        scored = [m for m in scored if m.score > 0.0]
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]


def _to_metadata_dict(value: dict | str) -> dict:
    return value if isinstance(value, dict) else json.loads(value)


class PgVectorStore:
    """Postgres-backed store, using a real `vector` column with an HNSW
    index (spec: Phase 11 RAG retrieval upgrade - see migrations 0002,
    0013, 0014 for the table's full history). Requires:

        CREATE TABLE vector_embeddings (
            namespace TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            embedding JSON NOT NULL,          -- legacy, kept as a rollback path
            metadata JSONB NOT NULL,
            embedding_vec vector(768),         -- real pgvector column
            text_search tsvector GENERATED ALWAYS AS (...) STORED,
            PRIMARY KEY (namespace, chunk_id)
        );

    `search` orders by `embedding_vec <=> :query` (HNSW-indexed) instead
    of fetching every row in the namespace and scoring in Python.
    `search_keyword` runs a real `ts_rank`/`plainto_tsquery` full-text
    query (GIN-indexed) for the keyword half of hybrid retrieval (see
    app.rag.retriever's RRF fusion of the two).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, namespace: str, chunk_id: str, embedding: list[float], metadata: dict
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO vector_embeddings (namespace, chunk_id, embedding, embedding_vec, metadata)
                VALUES (:namespace, :chunk_id, :embedding, CAST(:embedding_vec AS vector), :metadata)
                ON CONFLICT (namespace, chunk_id)
                DO UPDATE SET embedding = EXCLUDED.embedding,
                              embedding_vec = EXCLUDED.embedding_vec,
                              metadata = EXCLUDED.metadata
                """
            ),
            {
                "namespace": namespace,
                "chunk_id": chunk_id,
                "embedding": json.dumps(embedding),
                "embedding_vec": Vector(embedding).to_text(),
                "metadata": json.dumps(metadata),
            },
        )
        await self._session.flush()

    async def delete(self, *, namespace: str, chunk_id: str) -> None:
        await self._session.execute(
            text("DELETE FROM vector_embeddings WHERE namespace = :namespace AND chunk_id = :chunk_id"),
            {"namespace": namespace, "chunk_id": chunk_id},
        )
        await self._session.flush()

    async def search(
        self,
        *,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[VectorMatch]:
        rows = await self._session.execute(
            text(
                """
                SELECT chunk_id, metadata, 1 - (embedding_vec <=> CAST(:query_vec AS vector)) AS score
                FROM vector_embeddings
                WHERE namespace = :namespace
                  AND embedding_vec IS NOT NULL
                  AND (CAST(:filter_json AS jsonb) IS NULL OR metadata @> CAST(:filter_json AS jsonb))
                ORDER BY embedding_vec <=> CAST(:query_vec AS vector)
                LIMIT :top_k
                """
            ),
            {
                "namespace": namespace,
                "query_vec": Vector(query_embedding).to_text(),
                "filter_json": json.dumps(metadata_filter) if metadata_filter else None,
                "top_k": top_k,
            },
        )
        return [
            VectorMatch(chunk_id, float(score), _to_metadata_dict(metadata))
            for chunk_id, metadata, score in rows.all()
        ]

    async def search_keyword(
        self,
        *,
        namespace: str,
        query: str,
        top_k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[VectorMatch]:
        rows = await self._session.execute(
            text(
                """
                SELECT chunk_id, metadata, ts_rank(text_search, plainto_tsquery('english', :query)) AS score
                FROM vector_embeddings
                WHERE namespace = :namespace
                  AND text_search @@ plainto_tsquery('english', :query)
                  AND (CAST(:filter_json AS jsonb) IS NULL OR metadata @> CAST(:filter_json AS jsonb))
                ORDER BY score DESC
                LIMIT :top_k
                """
            ),
            {
                "namespace": namespace,
                "query": query,
                "filter_json": json.dumps(metadata_filter) if metadata_filter else None,
                "top_k": top_k,
            },
        )
        return [
            VectorMatch(chunk_id, float(score), _to_metadata_dict(metadata))
            for chunk_id, metadata, score in rows.all()
        ]


def get_vector_store(session: AsyncSession | None = None) -> VectorRepository:
    from app.config import get_settings

    settings = get_settings()
    if settings.vector_backend == "pgvector":
        if session is None:
            raise ValueError("pgvector backend requires a database session")
        return PgVectorStore(session)
    return InMemoryVectorStore()
