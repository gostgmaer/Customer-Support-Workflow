"""Embeddings (spec §8).

`HashingEmbedder` is a deterministic, dependency-free (numpy-only) feature-
hashing embedder: tokens are hashed into a fixed-size vector and L2
normalized, giving lexical-overlap-based similarity with zero external
calls or model downloads - sufficient for offline tests and as a
zero-setup fallback when no LLM API key is configured. `LangChainEmbedder`
wraps a real semantic embedding model (Google's `gemini-embedding-2` by
default) behind the same `Embedder` protocol for production-quality
retrieval; `get_embedder()` picks between them based on `settings.mock_llm`
and `settings.google_api_key`, mirroring how `MockLLMProvider` vs. a real
`LLMProvider` is already selected elsewhere in this codebase. The
retriever and vector store never depend on which one is active.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from app.observability.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _stable_hash(token: str) -> int:
    """A hash stable across processes/runs, unlike Python's randomized
    built-in `hash()` (PYTHONHASHSEED) - required so embeddings computed at
    ingestion time and at query time (possibly different processes) land in
    the same feature-hashed dimensions."""
    return int(hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest(), 16)


class Embedder(Protocol):
    dimensions: int
    model: str
    embedding_version: str

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    # `model`/`embedding_version` mirror `LangChainEmbedder`'s attributes
    # (spec: Phase 11 Tier 2.2 versioning) so app.rag.ingest can stamp
    # vector-store metadata uniformly without caring which embedder is
    # active - mixing hash-based and real-model vectors in the same
    # namespace silently would otherwise corrupt cosine comparisons.
    model = "hashing"

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions
        self.embedding_version = f"hashing-{dimensions}d"

    def _embed_sync(self, text: str) -> list[float]:
        vector = np.zeros(self.dimensions, dtype=float)
        tokens = _tokenize(text)
        if not tokens:
            return vector.tolist()
        for token in tokens:
            h = _stable_hash(token)
            index = h % self.dimensions
            sign = 1.0 if (h // self.dimensions) % 2 == 0 else -1.0
            vector[index] += sign
        norm = np.linalg.norm(vector) or 1.0
        return (vector / norm).tolist()

    async def embed(self, text: str) -> list[float]:
        return self._embed_sync(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_sync(t) for t in texts]


class LangChainEmbedder:
    """Wraps a real LangChain `Embeddings` model behind this module's
    `Embedder` protocol. `model`/`embedding_version` are exposed so
    ingestion can stamp which model produced a given vector (see
    app.rag.ingest) - mixing vectors from two different embedding models
    in the same vector-store namespace silently would otherwise corrupt
    cosine-similarity comparisons."""

    def __init__(self, langchain_embeddings: object, *, model: str, dimensions: int) -> None:
        self._impl = langchain_embeddings
        self.model = model
        self.embedding_version = model
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        return await self._impl.aembed_query(text)  # type: ignore[attr-defined]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await self._impl.aembed_documents(texts)  # type: ignore[attr-defined]


def get_embedder() -> Embedder:
    from app.config import get_settings

    settings = get_settings()
    if not settings.mock_llm and settings.google_api_key:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        impl = GoogleGenerativeAIEmbeddings(  # type: ignore[call-arg]
            model=settings.embedding_model,
            google_api_key=settings.google_api_key,
            output_dimensionality=settings.vector_dimensions,
        )
        return LangChainEmbedder(impl, model=settings.embedding_model, dimensions=settings.vector_dimensions)

    logger.info(
        "embedder_fallback_to_hashing",
        reason="mock_llm" if settings.mock_llm else "no_google_api_key",
    )
    return HashingEmbedder(dimensions=settings.vector_dimensions)
