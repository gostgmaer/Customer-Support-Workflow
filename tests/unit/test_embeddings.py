import pytest

from app.rag.embeddings import HashingEmbedder


@pytest.mark.asyncio
async def test_embedding_is_deterministic_across_instances():
    text = "refund policy for damaged items"
    a = await HashingEmbedder(dimensions=128).embed(text)
    b = await HashingEmbedder(dimensions=128).embed(text)
    assert a == b


@pytest.mark.asyncio
async def test_similar_text_has_higher_overlap_than_unrelated_text():
    import numpy as np

    embedder = HashingEmbedder(dimensions=128)
    base = np.array(await embedder.embed("refund policy for damaged items"))
    similar = np.array(await embedder.embed("policy for refunding a damaged item"))
    unrelated = np.array(await embedder.embed("quantum computing roadmap strategy"))

    sim_score = float(np.dot(base, similar))
    unrelated_score = float(np.dot(base, unrelated))
    assert sim_score > unrelated_score
