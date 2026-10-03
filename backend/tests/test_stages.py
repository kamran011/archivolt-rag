import uuid

from app.domains.rag.stages import build_stages, excluded
from app.domains.retrieval.schemas import RetrievedChunk


def chunk(title: str, score: float = 0.9, page: int | None = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title=title,
        content=f"content of {title} (never stored in traces)",
        score=score,
        metadata={"page_number": page} if page else {},
        retrieval_method="hybrid",
    )


def test_excluded_reports_only_dropped_chunks_with_reason():
    a, b, c = chunk("a"), chunk("b"), chunk("c")
    out = excluded([a, b, c], [a], "dedupe", "near_duplicate")
    assert {e["title"] for e in out} == {"b", "c"}
    assert all(e["stage"] == "dedupe" and e["reason"] == "near_duplicate" for e in out)


def test_build_stages_attributes_each_drop_to_the_right_stage():
    kept, weak, dup, over_budget, unranked = (
        chunk("kept"),
        chunk("weak", 0.01),
        chunk("dup"),
        chunk("budget"),
        chunk("unranked"),
    )
    candidates = [kept, weak, dup, over_budget, unranked]
    reranked = [kept, weak, dup, over_budget]  # 'unranked' fell outside rerank top_k
    after_score = [kept, dup, over_budget]  # 'weak' below min score
    filtered = [kept, over_budget]  # 'dup' removed as near-duplicate
    selected = [kept]  # 'budget' didn't fit in the context window

    s = build_stages(
        candidates=candidates,
        reranked=reranked,
        after_score=after_score,
        filtered=filtered,
        selected=selected,
        cited_chunk_ids=[kept.chunk_id],
    )
    reasons = {e["title"]: (e["stage"], e["reason"]) for e in s["excluded"]}
    assert reasons == {
        "unranked": ("rerank", "not_reranked"),
        "weak": ("score_filter", "below_min_score"),
        "dup": ("dedupe", "near_duplicate"),
        "budget": ("context", "context_budget"),
    }
    assert [x["title"] for x in s["selected"]] == ["kept"]
    assert s["cited"] == [str(kept.chunk_id)]
    assert len(s["retrieved"]) == 5


def test_stages_never_contain_chunk_text():
    c = chunk("secret-title")
    s = build_stages(
        candidates=[c], reranked=[c], after_score=[c], filtered=[c], selected=[c],
        cited_chunk_ids=[],
    )
    assert "content of" not in str(s)
