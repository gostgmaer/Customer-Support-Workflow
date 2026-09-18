"""Retrieval (spec §8-9).

Never returns expired policy documents (they are filtered out before
scoring, so an expired doc can never "win" over a current one) and applies
a similarity threshold: below it, the caller must not hallucinate an answer
- it should ask for clarification or escalate (see
app.workflow.nodes.knowledge_search / resolve_issue).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import get_settings
from app.observability.logging import get_logger
from app.observability.metrics import RETRIEVAL_HITS, RETRIEVAL_LATENCY
from app.rag.embeddings import Embedder, get_embedder
from app.rag.ingest import knowledge_namespace
from app.rag.reranker import rerank
from app.repositories.vector_store import VectorRepository

logger = get_logger(__name__)


@dataclass
class RetrievedDocument:
    document_id: str
    chunk_id: str
    title: str
    source: str
    category: str
    text: str
    score: float


def _is_current(metadata: dict, *, now: datetime) -> bool:
    expiration = metadata.get("expiration_date")
    if not expiration:
        return True
    try:
        expires_at = datetime.fromisoformat(expiration)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > now


class Retriever:
    def __init__(self, vector_store: VectorRepository, embedder: Embedder | None = None) -> None:
        self._vector_store = vector_store
        self._embedder = embedder or get_embedder()

    async def retrieve(
        self,
        query: str,
        *,
        tenant_id: str,
        top_k: int = 4,
        category: str | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedDocument]:
        """`min_score` overrides the env-var confidence_retrieval threshold
        for this call - lets a caller pass a tenant's DB-overridden value
        (spec §43, see app.workflow.nodes.route_nodes.knowledge_search_node)
        without this class needing to know DB overrides exist."""
        settings = get_settings()
        threshold = min_score if min_score is not None else settings.confidence_retrieval
        with RETRIEVAL_LATENCY.time():
            query_embedding = await self._embedder.embed(query)
            metadata_filter = {"category": category} if category else None
            raw_matches = await self._vector_store.search(
                namespace=knowledge_namespace(tenant_id),
                query_embedding=query_embedding,
                top_k=top_k * 3,
                metadata_filter=metadata_filter,
            )

        now = datetime.now(UTC)
        current_matches = [m for m in raw_matches if _is_current(m.metadata, now=now)]

        pairs = [(m, m.metadata.get("text", "")) for m in current_matches]
        reranked = rerank(query, pairs)

        seen_texts: set[str] = set()
        results: list[RetrievedDocument] = []
        for match, text, score in reranked:
            if score < threshold:
                continue
            dedup_key = text[:120]
            if dedup_key in seen_texts:
                continue
            seen_texts.add(dedup_key)
            results.append(
                RetrievedDocument(
                    document_id=match.metadata.get("document_id", ""),
                    chunk_id=match.metadata.get("chunk_id", match.chunk_id),
                    title=match.metadata.get("title", ""),
                    source=match.metadata.get("source", ""),
                    category=match.metadata.get("category", ""),
                    text=text,
                    score=score,
                )
            )
            if len(results) >= top_k:
                break

        RETRIEVAL_HITS.labels(hit="yes" if results else "no").inc()
        return results
