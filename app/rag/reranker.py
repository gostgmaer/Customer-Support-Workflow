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


def reciprocal_rank_fusion(
    ranked_lists: list[list[VectorMatch]], *, k: int = 60
) -> list[VectorMatch]:
    """Fuses multiple independently-ranked candidate lists (e.g. a vector
    search and a keyword search - see app.rag.retriever) into one ranking
    via Reciprocal Rank Fusion: `score = sum(1 / (k + rank))` across every
    list a chunk appears in, `rank` 0-indexed. `k=60` is RRF's standard
    default (Cormack et al., 2009) - it discounts rank differences deep in
    a list while still rewarding a chunk that ranks highly in more than
    one source. A chunk missing from a list simply doesn't contribute a
    term for it, so a keyword-only or vector-only match is never
    penalized for the source that didn't find it.

    Each returned `VectorMatch.score` is the RRF score (not a
    similarity/relevance score of either underlying method) - the caller
    (`rerank`) treats it as another ranking signal, not a probability or
    cosine similarity.
    """
    fused: dict[str, tuple[VectorMatch, float]] = {}
    for ranked_list in ranked_lists:
        for rank, match in enumerate(ranked_list):
            contribution = 1.0 / (k + rank)
            if match.chunk_id in fused:
                existing_match, existing_score = fused[match.chunk_id]
                fused[match.chunk_id] = (existing_match, existing_score + contribution)
            else:
                fused[match.chunk_id] = (match, contribution)

    results = [
        VectorMatch(match.chunk_id, score, match.metadata) for match, score in fused.values()
    ]
    results.sort(key=lambda m: m.score, reverse=True)
    return results


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
