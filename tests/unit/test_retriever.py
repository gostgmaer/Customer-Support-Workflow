"""Regression test for a real live-testing finding (spec: Phase 11): with
a real semantic embedder active, `Retriever` must weight the vector
cosine score heavily enough that a strong true match isn't outranked by
a lexically-similar-but-wrong document. Reproduces the exact shape of
the failure found live (a query sharing several literal words with the
wrong policy document) using a small fake non-hashing embedder, so this
never needs a real Google API call to test.
"""

from __future__ import annotations

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.rag.embeddings import HashingEmbedder
from app.rag.ingest import knowledge_namespace
from app.rag.retriever import Retriever
from app.repositories.vector_store import InMemoryVectorStore

_QUERY_VEC = [1.0, 0.0]
_RIGHT_DOC_VEC = [0.95, 0.312]  # cosine ~0.95 with the query - a strong true match
_WRONG_DOC_VEC = [0.8, 0.6]  # cosine ~0.8 - weaker, but the text below shares more words


class _FakeSemanticEmbedder:
    """Stands in for LangChainEmbedder - anything that isn't
    HashingEmbedder is treated by Retriever as a real, trustworthy
    semantic embedder."""

    model = "fake-semantic"
    embedding_version = "fake-semantic-v1"
    dimensions = 2

    async def embed(self, text: str) -> list[float]:
        return _QUERY_VEC

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [_QUERY_VEC for _ in texts]


@pytest.fixture(autouse=True)
def _reset_store():
    InMemoryVectorStore.reset()
    yield
    InMemoryVectorStore.reset()


async def _seed_conflicting_documents(
    vector_store: InMemoryVectorStore, *, dimensions: int = 2
) -> None:
    namespace = knowledge_namespace(DEFAULT_TENANT_ID)

    def _pad(vec: list[float]) -> list[float]:
        return vec + [0.0] * (dimensions - len(vec))

    await vector_store.upsert(
        namespace=namespace,
        chunk_id="right",
        embedding=_pad(_RIGHT_DOC_VEC),
        metadata={
            "document_id": "doc-right",
            "title": "Refund Policy",
            "source": "test",
            "category": "refunds",
            "text": "Customers may request a full refund within 30 days of delivery.",
        },
    )
    await vector_store.upsert(
        namespace=namespace,
        chunk_id="wrong",
        embedding=_pad(_WRONG_DOC_VEC),
        metadata={
            "document_id": "doc-wrong",
            "title": "Shipping Policy",
            "source": "test",
            "category": "shipping",
            "text": "Standard shipping takes 3-7 business days within the country of purchase.",
        },
    )


@pytest.mark.asyncio
async def test_semantic_embedder_uses_a_high_vector_weight_so_the_true_match_wins():
    vector_store = InMemoryVectorStore()
    await _seed_conflicting_documents(vector_store)

    retriever = Retriever(vector_store, embedder=_FakeSemanticEmbedder())
    results = await retriever.retrieve(
        "How many days can I return an item within of purchase?",
        tenant_id=DEFAULT_TENANT_ID,
        top_k=2,
        min_score=0.0,
    )

    assert results[0].title == "Refund Policy"


@pytest.mark.asyncio
async def test_retriever_passes_the_lexical_dominant_weight_for_hashing_embedder(monkeypatch):
    vector_store = InMemoryVectorStore()
    await _seed_conflicting_documents(vector_store, dimensions=64)
    seen_weights: list[float] = []

    import app.rag.retriever as retriever_module

    real_rerank = retriever_module.rerank

    def _spy_rerank(query, pairs, *, vector_weight=0.35):
        seen_weights.append(vector_weight)
        return real_rerank(query, pairs, vector_weight=vector_weight)

    monkeypatch.setattr(retriever_module, "rerank", _spy_rerank)

    retriever = Retriever(vector_store, embedder=HashingEmbedder(dimensions=64))
    await retriever.retrieve("anything", tenant_id=DEFAULT_TENANT_ID, top_k=2, min_score=0.0)

    assert seen_weights == [0.35]


@pytest.mark.asyncio
async def test_retriever_passes_the_semantic_weight_for_a_non_hashing_embedder(monkeypatch):
    vector_store = InMemoryVectorStore()
    await _seed_conflicting_documents(vector_store)
    seen_weights: list[float] = []

    import app.rag.retriever as retriever_module

    real_rerank = retriever_module.rerank

    def _spy_rerank(query, pairs, *, vector_weight=0.35):
        seen_weights.append(vector_weight)
        return real_rerank(query, pairs, vector_weight=vector_weight)

    monkeypatch.setattr(retriever_module, "rerank", _spy_rerank)

    from app.config import get_settings

    retriever = Retriever(vector_store, embedder=_FakeSemanticEmbedder())
    await retriever.retrieve("anything", tenant_id=DEFAULT_TENANT_ID, top_k=2, min_score=0.0)

    assert seen_weights == [get_settings().rerank_semantic_vector_weight]
