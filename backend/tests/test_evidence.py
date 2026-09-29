import uuid

from app.domains.retrieval.evidence import ContextAssembler, EvidenceFilter
from app.domains.retrieval.evidence_gate import EvidenceGate
from app.domains.retrieval.schemas import RetrievedChunk


def make_chunk(content: str = "some content", score: float = 0.5, page: int | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        content=content,
        score=score,
        metadata={"page_number": page} if page else {},
        retrieval_method="hybrid",
    )


# ─── EvidenceFilter.filter_by_score ─────────────────────────────────────────


def test_filter_by_score_removes_low_relevance_chunks():
    chunks = [make_chunk(score=0.8), make_chunk(score=0.1), make_chunk(score=0.5)]
    filtered = EvidenceFilter.filter_by_score(chunks, min_score=0.3)
    assert len(filtered) == 2
    assert all(c.score >= 0.3 for c in filtered)


def test_filter_by_score_keeps_all_above_threshold():
    chunks = [make_chunk(score=0.9), make_chunk(score=0.95)]
    filtered = EvidenceFilter.filter_by_score(chunks, min_score=0.3)
    assert len(filtered) == 2


def test_filter_by_score_empty_input():
    assert EvidenceFilter.filter_by_score([], min_score=0.3) == []


# ─── EvidenceFilter.deduplicate ─────────────────────────────────────────────


def test_deduplicate_removes_near_identical_content():
    chunks = [
        make_chunk("the quick brown fox jumps over the lazy dog", score=0.9),
        make_chunk("the quick brown fox jumps over the lazy dog today", score=0.8),
        make_chunk("completely different content about cats", score=0.7),
    ]
    deduped = EvidenceFilter.deduplicate(chunks, similarity_threshold=0.7)
    assert len(deduped) == 2


def test_deduplicate_keeps_higher_ranked_of_duplicate_pair():
    high = make_chunk("identical text here", score=0.9)
    low = make_chunk("identical text here", score=0.1)
    deduped = EvidenceFilter.deduplicate([high, low], similarity_threshold=0.5)
    assert len(deduped) == 1
    assert deduped[0].score == 0.9


def test_deduplicate_keeps_distinct_content():
    chunks = [make_chunk("alpha beta gamma"), make_chunk("delta epsilon zeta")]
    deduped = EvidenceFilter.deduplicate(chunks, similarity_threshold=0.9)
    assert len(deduped) == 2


# ─── ContextAssembler.assemble ──────────────────────────────────────────────


def test_context_assembler_respects_token_budget():
    long_content = " ".join(["word"] * 500)
    chunks = [make_chunk(long_content, score=0.9) for _ in range(10)]
    selected, total_tokens = ContextAssembler.assemble(chunks, max_tokens=1000)
    assert total_tokens <= 1000
    assert len(selected) < len(chunks)


def test_context_assembler_includes_all_when_under_budget():
    chunks = [make_chunk("short text", score=0.9) for _ in range(3)]
    selected, total_tokens = ContextAssembler.assemble(chunks, max_tokens=4096)
    assert len(selected) == 3


def test_context_assembler_empty_input():
    selected, total_tokens = ContextAssembler.assemble([], max_tokens=4096)
    assert selected == []
    assert total_tokens == 0


def test_context_assembler_format_with_citations():
    chunks = [
        make_chunk("First passage.", page=5),
        make_chunk("Second passage."),
    ]
    formatted = ContextAssembler.format_with_citations(chunks)
    assert "[Source 1 - Doc, p.5]:" in formatted
    assert "[Source 2 - Doc]:" in formatted
    assert "First passage." in formatted


# ─── EvidenceGate ────────────────────────────────────────────────────────────


def test_evidence_gate_fails_on_no_chunks():
    result = EvidenceGate.evaluate("some query", [])
    assert result.pass_gate is False
    assert result.chunk_count == 0
    assert "No evidence" in result.reason


def test_evidence_gate_fails_below_threshold():
    chunks = [make_chunk(score=0.1)]
    result = EvidenceGate.evaluate("query", chunks, min_relevance_threshold=0.25)
    assert result.pass_gate is False
    assert result.top_score == 0.1


def test_evidence_gate_passes_above_threshold():
    chunks = [make_chunk(score=0.6), make_chunk(score=0.3)]
    result = EvidenceGate.evaluate("query", chunks, min_relevance_threshold=0.25)
    assert result.pass_gate is True
    assert result.top_score == 0.6
    assert result.reason is None


def test_evidence_gate_uses_max_score_not_average():
    # One strong match should pass even if surrounded by weak ones
    chunks = [make_chunk(score=0.9), make_chunk(score=0.05), make_chunk(score=0.05)]
    result = EvidenceGate.evaluate("query", chunks, min_relevance_threshold=0.25)
    assert result.pass_gate is True
