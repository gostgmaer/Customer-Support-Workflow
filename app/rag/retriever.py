"""Retrieval (spec §8-9).

Never returns expired policy documents (they are filtered out before
scoring, so an expired doc can never "win" over a current one) and applies
a similarity threshold: below it, the caller must not hallucinate an answer
- it should ask for clarification or escalate (see
app.workflow.nodes.knowledge_search / resolve_issue).

Retrieval is hybrid (spec: Phase 11 RAG retrieval upgrade): a vector
search and an independent keyword search are run side by side and fused
via Reciprocal Rank Fusion before the existing lexical-boost `rerank()`
step - a document the embedding step fails to surface can still be
recovered by an exact keyword match, which a vector-only pipeline (the
previous behavior) could never do.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import get_settings
from app.observability.logging import get_logger
from app.observability.metrics import (
    EMBEDDING_LATENCY,
    KEYWORD_SEARCH_LATENCY,
    RERANK_LATENCY,
    RETRIEVAL_HITS,
    RETRIEVAL_LATENCY,
    VECTOR_SEARCH_LATENCY,
)
from app.rag.embeddings import Embedder, HashingEmbedder, get_embedder
from app.rag.ingest import knowledge_namespace
from app.rag.reranker import reciprocal_rank_fusion, rerank
from app.repositories.vector_store import VectorMatch, VectorRepository

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
        namespace = knowledge_namespace(tenant_id)
        metadata_filter = {"category": category} if category else None

        with RETRIEVAL_LATENCY.time():
            embed_start = time.perf_counter()
            query_embedding = await self._embedder.embed(query)
            EMBEDDING_LATENCY.observe(time.perf_counter() - embed_start)

            vector_start = time.perf_counter()
            vector_matches = await self._vector_store.search(
                namespace=namespace,
                query_embedding=query_embedding,
                top_k=top_k * 3,
                metadata_filter=metadata_filter,
            )
            VECTOR_SEARCH_LATENCY.observe(time.perf_counter() - vector_start)

            keyword_start = time.perf_counter()
            try:
                keyword_matches = await self._vector_store.search_keyword(
                    namespace=namespace,
                    query=query,
                    top_k=top_k * 3,
                    metadata_filter=metadata_filter,
                )
            except Exception:
                # Hybrid retrieval is additive over the vector-only baseline
                # - a keyword-search failure (e.g. a backend that hasn't run
                # migration 0014 yet) must never take down retrieval
                # entirely, only fall back to vector-only for this query.
                logger.warning("keyword_search_failed", query=query, tenant_id=tenant_id, exc_info=True)
                keyword_matches = []
            KEYWORD_SEARCH_LATENCY.observe(time.perf_counter() - keyword_start)

            rerank_start = time.perf_counter()
            now = datetime.now(UTC)
            # RRF's fused score (~1/(2*60) for a double-hit, down to
            # 1/(60+rank) for a single-list hit) lives on a completely
            # different scale than the cosine similarity `rerank()` expects
            # in `match.score` - feeding it straight in would silently
            # collapse every combined score under the confidence threshold
            # (confirmed: it did, in this exact form, before this fix).
            # RRF here only decides *which* chunks matter and their
            # relative order; each candidate's `.score` going into
            # `rerank()` is its real vector cosine similarity when vector
            # search found it, or 0.0 when it was recovered by keyword
            # search alone - `rerank()`'s independently-computed
            # lexical-overlap term is what lets a keyword-only recovery
            # still clear the threshold, not a borrowed RRF number.
            fused_order = reciprocal_rank_fusion([vector_matches, keyword_matches])
            vector_by_chunk_id = {m.chunk_id: m for m in vector_matches}
            fused = [
                vector_by_chunk_id.get(m.chunk_id) or VectorMatch(m.chunk_id, 0.0, m.metadata)
                for m in fused_order
            ]
            current_matches = [m for m in fused if _is_current(m.metadata, now=now)]

            pairs = [(m, m.metadata.get("text", "")) for m in current_matches]
            # A real embedder's cosine score is a far more reliable signal
            # than this codebase's crude lexical-overlap score (no IDF
            # weighting - a query sharing a few common words with the
            # WRONG document can otherwise outrank the right one despite
            # a clearly stronger vector match; live-verified, see
            # settings.rerank_semantic_vector_weight's own docstring for
            # the exact reproduction). HashingEmbedder keeps rerank()'s
            # own lexical-dominant 0.35 default, calibrated for its
            # coarser, noisier cosine scores.
            vector_weight = (
                0.35
                if isinstance(self._embedder, HashingEmbedder)
                else settings.rerank_semantic_vector_weight
            )
            reranked = rerank(query, pairs, vector_weight=vector_weight)
            RERANK_LATENCY.observe(time.perf_counter() - rerank_start)

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
        logger.info(
            "rag_retrieval",
            query=query,
            tenant_id=tenant_id,
            category=category,
            semantic_candidates=len(vector_matches),
            keyword_candidates=len(keyword_matches),
            fused_candidates=len(fused),
            final_chunks=len(results),
            threshold=threshold,
        )
        return results
