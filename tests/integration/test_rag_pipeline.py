from pathlib import Path

import pytest

from app.db.base import DEFAULT_TENANT_ID
from app.rag.ingest import ingest_knowledge_directory
from app.rag.retriever import Retriever
from app.repositories.vector_store import InMemoryVectorStore

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "seed" / "knowledge"


@pytest.mark.asyncio
async def test_ingest_and_retrieve_current_refund_policy(db_session):
    count = await ingest_knowledge_directory(KNOWLEDGE_DIR, db_session)
    assert count > 0

    retriever = Retriever(InMemoryVectorStore())
    results = await retriever.retrieve(
        "What is your refund policy for damaged items?", tenant_id=DEFAULT_TENANT_ID, top_k=3
    )

    assert results, "expected at least one retrieved document"
    titles = {r.title for r in results}
    assert "Refund Policy" in titles
    assert "Refund Policy (2024, superseded)" not in titles, "expired policy must never be surfaced"


@pytest.mark.asyncio
async def test_retrieval_below_threshold_returns_empty(db_session):
    await ingest_knowledge_directory(KNOWLEDGE_DIR, db_session)
    retriever = Retriever(InMemoryVectorStore())
    results = await retriever.retrieve(
        "asdkjqwoe unrelated gibberish xyzzy plugh", tenant_id=DEFAULT_TENANT_ID, top_k=3
    )
    assert results == []


@pytest.mark.asyncio
async def test_retrieval_is_isolated_per_tenant(db_session):
    """spec §43: 'Vector retrieval must support tenant isolation' - a
    document ingested for one tenant must never surface in another
    tenant's retrieval, even with an identical query."""
    await ingest_knowledge_directory(KNOWLEDGE_DIR, db_session, tenant_id="tenant_a")

    retriever = Retriever(InMemoryVectorStore())
    tenant_a_results = await retriever.retrieve(
        "What is your refund policy for damaged items?", tenant_id="tenant_a", top_k=3
    )
    tenant_b_results = await retriever.retrieve(
        "What is your refund policy for damaged items?", tenant_id="tenant_b", top_k=3
    )

    assert tenant_a_results, "tenant_a should see its own ingested documents"
    assert tenant_b_results == [], "tenant_b must not see tenant_a's documents"
