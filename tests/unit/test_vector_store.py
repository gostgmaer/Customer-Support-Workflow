import pytest

from app.repositories.vector_store import InMemoryVectorStore


@pytest.fixture(autouse=True)
def _reset_store():
    InMemoryVectorStore.reset()
    yield
    InMemoryVectorStore.reset()


@pytest.mark.asyncio
async def test_search_keyword_finds_an_exact_lexical_match():
    store = InMemoryVectorStore()
    await store.upsert(
        namespace="ns",
        chunk_id="a",
        embedding=[0.0, 0.0],
        metadata={"text": "our refund policy covers damaged items"},
    )
    await store.upsert(
        namespace="ns",
        chunk_id="b",
        embedding=[0.0, 0.0],
        metadata={"text": "unrelated shipping information"},
    )

    results = await store.search_keyword(namespace="ns", query="refund policy", top_k=5)

    assert [m.chunk_id for m in results] == ["a"]


@pytest.mark.asyncio
async def test_search_keyword_returns_nothing_for_zero_overlap():
    store = InMemoryVectorStore()
    await store.upsert(
        namespace="ns", chunk_id="a", embedding=[0.0], metadata={"text": "totally unrelated content"}
    )

    results = await store.search_keyword(namespace="ns", query="refund policy", top_k=5)

    assert results == []


@pytest.mark.asyncio
async def test_search_keyword_respects_namespace_isolation():
    store = InMemoryVectorStore()
    await store.upsert(
        namespace="tenant_a", chunk_id="a", embedding=[0.0], metadata={"text": "refund policy"}
    )

    results = await store.search_keyword(namespace="tenant_b", query="refund policy", top_k=5)

    assert results == []


@pytest.mark.asyncio
async def test_search_keyword_respects_metadata_filter():
    store = InMemoryVectorStore()
    await store.upsert(
        namespace="ns",
        chunk_id="a",
        embedding=[0.0],
        metadata={"text": "refund policy details", "category": "billing"},
    )
    await store.upsert(
        namespace="ns",
        chunk_id="b",
        embedding=[0.0],
        metadata={"text": "refund policy details", "category": "shipping"},
    )

    results = await store.search_keyword(
        namespace="ns", query="refund policy", top_k=5, metadata_filter={"category": "billing"}
    )

    assert [m.chunk_id for m in results] == ["a"]
