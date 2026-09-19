import pytest

from app.rag.embeddings import HashingEmbedder, LangChainEmbedder, get_embedder


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


class _FakeLangChainEmbeddings:
    """Stands in for GoogleGenerativeAIEmbeddings behind LangChainEmbedder,
    matching MockLLMProvider's own precedent of never making a real API
    call from the test suite."""

    async def aembed_query(self, text: str) -> list[float]:
        return [1.0, 2.0, 3.0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 2.0, 3.0] for _ in texts]


@pytest.mark.asyncio
async def test_langchain_embedder_delegates_to_the_wrapped_impl():
    embedder = LangChainEmbedder(_FakeLangChainEmbeddings(), model="fake-model", dimensions=3)
    assert await embedder.embed("hello") == [1.0, 2.0, 3.0]
    assert await embedder.embed_batch(["a", "b"]) == [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]
    assert embedder.model == "fake-model"
    assert embedder.embedding_version == "fake-model"


@pytest.mark.asyncio
async def test_langchain_embedder_embed_batch_of_nothing_is_a_noop():
    embedder = LangChainEmbedder(_FakeLangChainEmbeddings(), model="fake-model", dimensions=3)
    assert await embedder.embed_batch([]) == []


def test_get_embedder_falls_back_to_hashing_when_mock_llm(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_LLM", "true")
    get_settings.cache_clear()
    try:
        assert isinstance(get_embedder(), HashingEmbedder)
    finally:
        get_settings.cache_clear()


def test_get_embedder_falls_back_to_hashing_without_google_api_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_LLM", "false")
    # Explicitly blank, not delenv: this project's .env may itself define a
    # real GOOGLE_API_KEY (pydantic-settings' env_file is a fallback source
    # underneath os.environ, so delenv alone wouldn't actually unset it).
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    get_settings.cache_clear()
    try:
        assert isinstance(get_embedder(), HashingEmbedder)
    finally:
        get_settings.cache_clear()


def test_get_embedder_uses_langchain_when_a_real_provider_is_configured(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MOCK_LLM", "false")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-not-real")
    get_settings.cache_clear()
    try:
        embedder = get_embedder()
        assert isinstance(embedder, LangChainEmbedder)
        assert embedder.model == get_settings().embedding_model
    finally:
        get_settings.cache_clear()


def test_hashing_embedder_exposes_model_and_embedding_version():
    embedder = HashingEmbedder(dimensions=64)
    assert embedder.model == "hashing"
    assert embedder.embedding_version == "hashing-64d"
