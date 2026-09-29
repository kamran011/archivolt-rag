from app.domains.ingestion.chunkers.fixed_chunker import FixedChunker
from app.domains.ingestion.chunkers.structure_aware_chunker import StructureAwareChunker
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage


def make_doc(elements: list[DocumentElement], page_number: int = 1) -> ParsedDocument:
    return ParsedDocument(
        title="Test Doc",
        pages=[ParsedPage(page_number=page_number, elements=elements)],
    )


def test_fixed_chunker_respects_token_budget():
    long_text = " ".join([f"Sentence number {i}." for i in range(200)])
    doc = make_doc([DocumentElement(type="paragraph", content=long_text, page_number=1)])

    chunker = FixedChunker()
    chunks = chunker.chunk(doc, chunk_size=100, chunk_overlap=20)

    assert len(chunks) > 1
    for chunk in chunks:
        # Allow slight overshoot since we don't split mid-sentence
        assert chunk.token_count <= 150


def test_fixed_chunker_produces_overlap():
    long_text = " ".join([f"Sentence number {i}." for i in range(100)])
    doc = make_doc([DocumentElement(type="paragraph", content=long_text, page_number=1)])

    chunker = FixedChunker()
    chunks = chunker.chunk(doc, chunk_size=80, chunk_overlap=20)

    assert len(chunks) >= 2
    # Some words from the end of chunk 0 should reappear at the start of chunk 1
    chunk0_tail = chunks[0].content.split()[-3:]
    chunk1_head = chunks[1].content.split()[:10]
    assert any(word in chunk1_head for word in chunk0_tail)


def test_fixed_chunker_empty_document():
    doc = make_doc([])
    chunker = FixedChunker()
    chunks = chunker.chunk(doc, chunk_size=512, chunk_overlap=64)
    assert chunks == []


def test_structure_aware_chunker_preserves_heading_hierarchy():
    elements = [
        DocumentElement(type="heading", content="Chapter 1", level=1, page_number=1),
        DocumentElement(type="heading", content="Section 1.1", level=2, page_number=1),
        DocumentElement(
            type="paragraph", content="This is the content of section 1.1.", page_number=1
        ),
    ]
    doc = make_doc(elements)

    chunker = StructureAwareChunker()
    chunks = chunker.chunk(doc, chunk_size=512, chunk_overlap=64)

    assert len(chunks) == 1
    assert chunks[0].metadata["heading_hierarchy"] == ["Chapter 1", "Section 1.1"]
    assert "Chapter 1 > Section 1.1" in chunks[0].content
    assert "content of section 1.1" in chunks[0].content


def test_structure_aware_chunker_splits_oversized_section():
    long_text = " ".join([f"Word{i}" for i in range(2000)])
    elements = [
        DocumentElement(type="heading", content="Big Section", level=1, page_number=1),
        DocumentElement(type="paragraph", content=long_text, page_number=1),
    ]
    doc = make_doc(elements)

    chunker = StructureAwareChunker()
    chunks = chunker.chunk(doc, chunk_size=200, chunk_overlap=20)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.metadata["heading_hierarchy"] == ["Big Section"]
        assert chunk.metadata.get("split_from_oversized_section") is True


def test_structure_aware_chunker_falls_back_without_headings():
    long_text = " ".join([f"Sentence {i}." for i in range(100)])
    doc = make_doc([DocumentElement(type="paragraph", content=long_text, page_number=1)])

    chunker = StructureAwareChunker()
    chunks = chunker.chunk(doc, chunk_size=100, chunk_overlap=10)

    assert len(chunks) > 0


def test_structure_aware_chunker_nested_hierarchy_pops_correctly():
    elements = [
        DocumentElement(type="heading", content="Ch1", level=1, page_number=1),
        DocumentElement(type="heading", content="Sec1", level=2, page_number=1),
        DocumentElement(type="paragraph", content="First content.", page_number=1),
        DocumentElement(type="heading", content="Sec2", level=2, page_number=1),
        DocumentElement(type="paragraph", content="Second content.", page_number=1),
        DocumentElement(type="heading", content="Ch2", level=1, page_number=1),
        DocumentElement(type="paragraph", content="Third content.", page_number=1),
    ]
    doc = make_doc(elements)

    chunker = StructureAwareChunker()
    chunks = chunker.chunk(doc, chunk_size=512, chunk_overlap=64)

    hierarchies = [c.metadata["heading_hierarchy"] for c in chunks]
    assert ["Ch1", "Sec1"] in hierarchies
    assert ["Ch1", "Sec2"] in hierarchies
    assert ["Ch2"] in hierarchies
