"""Embeddings (spec §8).

`HashingEmbedder` is a deterministic, dependency-free (numpy-only) feature-
hashing embedder: tokens are hashed into a fixed-size vector and L2
normalized, giving lexical-overlap-based similarity with zero external
calls or model downloads - sufficient for the curated seed knowledge base
and for offline tests. Swap `Embedder` for a real embeddings API/model
behind this same interface for production-quality semantic retrieval; the
retriever and vector store never depend on which one is active.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

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

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

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


def get_embedder() -> Embedder:
    from app.config import get_settings

    return HashingEmbedder(dimensions=get_settings().vector_dimensions)
