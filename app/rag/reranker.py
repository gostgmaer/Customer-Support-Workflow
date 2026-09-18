"""Reranking (spec §9).

Combines the vector similarity score with a cheap lexical-overlap score so
an exact keyword match (e.g. "refund window") can outrank a vector match
that is merely topically related - useful given the hashing embedder's
coarse semantics.
"""

from __future__ import annotations

import re

from app.repositories.vector_store import VectorMatch

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def lexical_overlap(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    text_tokens = _tokens(text)
    return len(query_tokens & text_tokens) / len(query_tokens)


def rerank(
    query: str, matches: list[tuple[VectorMatch, str]], *, vector_weight: float = 0.35
) -> list[tuple[VectorMatch, str, float]]:
    """`matches` is (VectorMatch, chunk_text) pairs. Returns
    (match, text, combined_score) sorted descending by combined_score.

    Weighted toward lexical overlap by default: the hashing embedder's
    cosine similarities are coarse (typically 0.05-0.4 even for a strong
    match), so weighting it like a real semantic embedding model would
    wash out the more reliable keyword signal. Turn `vector_weight` back up
    if `HashingEmbedder` is swapped for a real embedding model/API."""
    scored = []
    for match, text in matches:
        lexical = lexical_overlap(query, text)
        combined = vector_weight * match.score + (1 - vector_weight) * lexical
        scored.append((match, text, combined))
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored
