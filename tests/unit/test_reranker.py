from app.rag.reranker import lexical_overlap, reciprocal_rank_fusion, rerank
from app.repositories.vector_store import VectorMatch


def test_lexical_overlap_full_match_scores_one():
    assert lexical_overlap("refund policy", "our refund policy covers damaged items") == 1.0


def test_lexical_overlap_no_shared_tokens_scores_zero():
    assert lexical_overlap("refund policy", "quantum computing roadmap") == 0.0


def test_rerank_orders_by_combined_score_descending():
    matches = [
        (VectorMatch("a", 0.9, {}), "totally unrelated text about astronomy"),
        (VectorMatch("b", 0.1, {}), "refund policy for damaged items"),
    ]
    reranked = rerank("refund policy damaged items", matches, vector_weight=0.35)
    assert [m.chunk_id for m, _text, _score in reranked] == ["b", "a"]


def test_reciprocal_rank_fusion_rewards_a_chunk_ranked_in_both_lists():
    # "shared" ranks #2 in the vector list and #1 in the keyword list;
    # "vector_only" ranks #1 in the vector list but never appears in the
    # keyword list. Hand-computed RRF scores (k=60):
    #   shared      = 1/(60+1) + 1/(60+0) = 0.016393... + 0.016667... = 0.033060...
    #   vector_only = 1/(60+0)                                        = 0.016667...
    # A double-hit chunk should outrank a chunk that only ever appeared
    # once, even at a better individual rank.
    vector_list = [
        VectorMatch("vector_only", 0.99, {"text": "vector only"}),
        VectorMatch("shared", 0.50, {"text": "shared chunk"}),
    ]
    keyword_list = [
        VectorMatch("shared", 5.0, {"text": "shared chunk"}),
    ]
    fused = reciprocal_rank_fusion([vector_list, keyword_list])
    assert [m.chunk_id for m in fused] == ["shared", "vector_only"]
    assert fused[0].score == 1 / 61 + 1 / 60
    assert fused[1].score == 1 / 60


def test_reciprocal_rank_fusion_of_empty_lists_is_empty():
    assert reciprocal_rank_fusion([[], []]) == []


def test_reciprocal_rank_fusion_preserves_metadata_from_a_contributing_match():
    vector_list = [VectorMatch("a", 0.9, {"text": "hello", "title": "Doc A"})]
    fused = reciprocal_rank_fusion([vector_list, []])
    assert fused[0].metadata == {"text": "hello", "title": "Doc A"}
