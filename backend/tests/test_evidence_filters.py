import uuid

from app.domains.rag.stages import build_stages
from app.domains.retrieval.evidence import EvidenceFilter
from app.domains.retrieval.schemas import RetrievedChunk


def chunk(content, score=0.9, doc=None, current=True, tier="standard") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=doc or uuid.uuid4(),
        document_title="d",
        content=content,
        score=score,
        metadata={},
        retrieval_method="hybrid",
        is_current=current,
        authority_tier=tier,
    )


def test_superseded_removed_when_current_evidence_exists():
    cur, old = chunk("current text"), chunk("old text", current=False)
    assert EvidenceFilter.remove_superseded([old, cur]) == [cur]


def test_superseded_kept_when_nothing_current():
    old = chunk("old", current=False)
    assert EvidenceFilter.remove_superseded([old]) == [old]


def test_drafts_removed_only_when_reviewed_evidence_exists():
    draft, std, auth = chunk("d", tier="draft"), chunk("s"), chunk("a", tier="authoritative")
    assert EvidenceFilter.remove_low_authority([draft, std, auth]) == [std, auth]
    assert EvidenceFilter.remove_low_authority([draft]) == [draft]


def test_per_document_cap_keeps_best_chunks_and_other_documents():
    big, small = uuid.uuid4(), uuid.uuid4()
    chunks = [chunk(f"big {i}", 0.9 - i * 0.01, doc=big) for i in range(5)] + [
        chunk("small", 0.5, doc=small)
    ]
    kept = EvidenceFilter.limit_per_document(chunks, 2)
    assert [c.content for c in kept] == ["big 0", "big 1", "small"]


def test_pipeline_labels_every_drop_with_its_own_stage():
    doc = uuid.uuid4()
    good = chunk("refund policy thirty days annual plans", 0.9, doc=doc)
    weak = chunk("unrelated", 0.01)
    stale = chunk("old refund policy sixty days", 0.8, current=False)
    draft = chunk("draft refund policy ninety days", 0.8, tier="draft")
    dup = chunk("refund policy thirty days annual plans", 0.85)  # same words as `good`
    capped = [chunk(f"filler passage {i} distinct words{i}", 0.7, doc=doc) for i in range(6)]

    after_score, out = EvidenceFilter.run_pipeline(
        [good, weak, stale, draft, dup, *capped], max_per_document=3
    )
    dropped = {c.chunk_id: (stage, reason) for c, stage, reason in out.dropped}

    assert weak not in after_score  # removed by the score filter, not part of the pipeline drops
    assert dropped[stale.chunk_id] == ("stale", "superseded_version")
    assert dropped[draft.chunk_id] == ("authority", "lower_authority_than_available")
    assert dropped[dup.chunk_id] == ("dedupe", "near_duplicate")
    assert {dropped[c.chunk_id] for c in capped[3:]} == {("diversity", "document_cap")}
    assert good in out.kept and len([c for c in out.kept if c.document_id == doc]) == 3


def test_pipeline_keeps_superseded_for_historical_questions():
    old = chunk("policy as of 2022", current=False)
    cur = chunk("policy today words different", 0.8)
    _, out = EvidenceFilter.run_pipeline([old, cur], keep_superseded=True)
    assert old in out.kept and cur in out.kept


def test_build_stages_uses_pipeline_reasons_in_the_trace():
    good = chunk("good passage about refunds")
    stale = chunk("old passage", current=False)
    reranked = [good, stale]
    after_score, out = EvidenceFilter.run_pipeline(reranked)
    s = build_stages(
        candidates=reranked,
        reranked=reranked,
        after_score=after_score,
        filtered=out.kept,
        selected=out.kept,
        cited_chunk_ids=[],
        filter_drops=out.dropped,
    )
    assert [(e["stage"], e["reason"]) for e in s["excluded"]] == [("stale", "superseded_version")]
