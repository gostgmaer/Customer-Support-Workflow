"""Vector store abstraction (spec §28).

`VectorRepository` is the interface the RAG retriever depends on. Two
implementations are provided, selected by `VECTOR_BACKEND`:

- `InMemoryVectorStore` (default): numpy cosine similarity, process-local.
  Zero setup, fine for the curated seed corpus and for tests.
- `PgVectorStore`: persists embeddings as JSON float arrays in Postgres and
  scores in Python after a metadata-filtered fetch. This avoids requiring
  the postgres `vector` extension to be installed for this build; swap the
  storage/query in this class for a real `vector` column + `<->` operator
  (via the `pgvector` package) for large-corpus production use without
  touching the retriever - the interface does not change.

Both implementations support metadata filtering, namespace isolation,
upsert, and delete, per spec.
"""

from __future__ import annotations

import json
from typing import Protocol

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


class PgVectorStore:
    """Postgres-backed store. Requires the `vector_embeddings` table

        CREATE TABLE vector_embeddings (
            namespace TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            embedding JSONB NOT NULL,
            metadata JSONB NOT NULL,
            PRIMARY KEY (namespace, chunk_id)
        );

    which is created by migration 0002 (see migrations/versions).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, namespace: str, chunk_id: str, embedding: list[float], metadata: dict
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO vector_embeddings (namespace, chunk_id, embedding, metadata)
                VALUES (:namespace, :chunk_id, :embedding, :metadata)
                ON CONFLICT (namespace, chunk_id)
                DO UPDATE SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
                """
            ),
            {
                "namespace": namespace,
                "chunk_id": chunk_id,
                "embedding": json.dumps(embedding),
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
            text("SELECT chunk_id, embedding, metadata FROM vector_embeddings WHERE namespace = :namespace"),
            {"namespace": namespace},
        )
        query = np.array(query_embedding, dtype=float)
        scored = []
        for chunk_id, embedding_json, metadata_json in rows.all():
            metadata = metadata_json if isinstance(metadata_json, dict) else json.loads(metadata_json)
            if not _matches_filter(metadata, metadata_filter):
                continue
            embedding = embedding_json if isinstance(embedding_json, list) else json.loads(embedding_json)
            score = _cosine(query, np.array(embedding, dtype=float))
            scored.append(VectorMatch(chunk_id, score, metadata))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]


def get_vector_store(session: AsyncSession | None = None) -> VectorRepository:
    from app.config import get_settings

    settings = get_settings()
    if settings.vector_backend == "pgvector":
        if session is None:
            raise ValueError("pgvector backend requires a database session")
        return PgVectorStore(session)
    return InMemoryVectorStore()
