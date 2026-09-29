import uuid

from app.domains.retrieval.rrf import reciprocal_rank_fusion
from app.domains.retrieval.schemas import RetrievedChunk


def make_chunk(chunk_id: uuid.UUID, method: str, score: float = 1.0, **extra) -> RetrievedChunk:
    defaults = dict(
        chunk_id=chunk_id,
        document_id=uuid.uuid4(),
        document_title="Doc",
        content="content",
        score=score,
        metadata={},
        retrieval_method=method,
    )
    defaults.update(extra)
    return RetrievedChunk(**defaults)


def test_rrf_ranks_chunk_appearing_in_both_lists_highest():
    shared_id = uuid.uuid4()
    only_semantic_id = uuid.uuid4()
    only_keyword_id = uuid.uuid4()

    semantic = [make_chunk(shared_id, "semantic"), make_chunk(only_semantic_id, "semantic")]
    keyword = [make_chunk(shared_id, "keyword"), make_chunk(only_keyword_id, "keyword")]

    fused = reciprocal_rank_fusion([semantic, keyword])

    assert fused[0].chunk_id == shared_id
    assert fused[0].retrieval_method == "hybrid"


def test_rrf_preserves_all_unique_chunks():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    semantic = [make_chunk(a, "semantic"), make_chunk(b, "semantic")]
    keyword = [make_chunk(c, "keyword")]

    fused = reciprocal_rank_fusion([semantic, keyword])

    fused_ids = {c.chunk_id for c in fused}
    assert fused_ids == {a, b, c}


def test_rrf_higher_rank_scores_higher_within_same_list():
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    semantic = [
        make_chunk(first, "semantic"),
        make_chunk(second, "semantic"),
        make_chunk(third, "semantic"),
    ]

    fused = reciprocal_rank_fusion([semantic])

    assert [c.chunk_id for c in fused] == [first, second, third]
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_empty_lists_return_empty():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_rrf_single_list_preserves_single_method():
    only_id = uuid.uuid4()
    fused = reciprocal_rank_fusion([[make_chunk(only_id, "keyword")]])
    assert fused[0].retrieval_method == "keyword"


def test_rrf_score_formula_matches_expected_values():
    a = uuid.uuid4()
    # a is rank 1 in list 1 (k=60): score = 1/61
    fused = reciprocal_rank_fusion([[make_chunk(a, "semantic")]], k=60)
    assert abs(fused[0].score - (1.0 / 61)) < 1e-9

    # a is rank 1 in both lists: score = 1/61 + 1/61
    fused2 = reciprocal_rank_fusion(
        [[make_chunk(a, "semantic")], [make_chunk(a, "keyword")]], k=60
    )
    assert abs(fused2[0].score - (2.0 / 61)) < 1e-9


def test_rrf_preserves_authority_and_freshness_fields():
    """Regression test: fusion previously reconstructed RetrievedChunk manually
    and silently dropped is_current/authority_tier/version/effective_date."""
    chunk_id = uuid.uuid4()
    chunk = make_chunk(
        chunk_id,
        "semantic",
        is_current=False,
        authority_tier="authoritative",
        document_version=3,
    )
    fused = reciprocal_rank_fusion([[chunk]])
    assert fused[0].is_current is False
    assert fused[0].authority_tier == "authoritative"
    assert fused[0].document_version == 3
