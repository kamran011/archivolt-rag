import uuid

from app.domains.rag.citation_parser import CitationParser
from app.domains.retrieval.schemas import RetrievedChunk


def make_chunk(content: str = "content", page: int | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="Doc",
        content=content,
        score=0.8,
        metadata={"page_number": page} if page else {},
        retrieval_method="hybrid",
    )


def test_parses_single_citation():
    chunks = [make_chunk("evidence text")]
    answer = "The policy allows refunds [Source 1]."
    citations = CitationParser.parse_citations(answer, chunks)
    assert len(citations) == 1
    assert citations[0].index == 1
    assert citations[0].content == "evidence text"


def test_parses_multiple_citations_in_order():
    chunks = [make_chunk("first"), make_chunk("second"), make_chunk("third")]
    answer = "Claim A [Source 2]. Claim B [Source 1]. Claim C [Source 3]."
    citations = CitationParser.parse_citations(answer, chunks)
    assert [c.index for c in citations] == [1, 2, 3]


def test_deduplicates_repeated_source_references():
    chunks = [make_chunk("evidence")]
    answer = "Claim A [Source 1]. Claim B also supported [Source 1]."
    citations = CitationParser.parse_citations(answer, chunks)
    assert len(citations) == 1


def test_rejects_citation_index_beyond_supplied_evidence():
    """Critical hallucination guard: a fabricated [Source 99] must never produce
    a citation, since no such evidence was actually supplied to the model."""
    chunks = [make_chunk("only evidence")]
    answer = "This claim cites a source that doesn't exist [Source 99]."
    citations = CitationParser.parse_citations(answer, chunks)
    assert citations == []


def test_rejects_citation_index_zero_or_negative():
    chunks = [make_chunk("evidence")]
    answer = "Weird citation [Source 0]."
    citations = CitationParser.parse_citations(answer, chunks)
    assert citations == []


def test_no_citations_in_answer_returns_empty():
    chunks = [make_chunk("evidence")]
    answer = "This answer has no citation markers at all."
    citations = CitationParser.parse_citations(answer, chunks)
    assert citations == []


def test_citation_includes_page_number_from_metadata():
    chunks = [make_chunk("evidence", page=42)]
    answer = "Claim [Source 1]."
    citations = CitationParser.parse_citations(answer, chunks)
    assert citations[0].page_number == 42


def test_empty_chunks_never_produce_citations():
    answer = "This claims [Source 1] but no evidence was supplied."
    citations = CitationParser.parse_citations(answer, [])
    assert citations == []
