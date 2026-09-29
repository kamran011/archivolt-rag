from unittest.mock import AsyncMock, patch

import pymupdf as fitz
import pytest

from app.config import settings
from app.domains.ingestion.chunkers.base import BaseChunker
from app.domains.ingestion.chunkers.structure_aware_chunker import StructureAwareChunker
from app.domains.ingestion.chunkers.table import rows_to_markdown, split_table
from app.domains.ingestion.parsers.pdf_parser import PDFParser, _transcription_to_elements
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage
from app.providers.vision import VisionResult

count = BaseChunker.count_tokens.__get__(StructureAwareChunker())


def make_table(n_rows: int) -> str:
    lines = ["| Item | Price |", "| --- | --- |"]
    lines += [f"| item-{i} | ${i}.00 |" for i in range(n_rows)]
    return "\n".join(lines)


# ── table helpers ────────────────────────────────────────────────────────────

def test_rows_to_markdown_escapes_and_pads():
    md = rows_to_markdown([["A", "B|x"], ["1"], [None, None]])
    lines = md.split("\n")
    assert lines[0] == "| A | B\\|x |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 |  |"
    assert len(lines) == 3  # fully empty row dropped


def test_small_table_not_split():
    t = make_table(3)
    assert split_table(t, 500, count) == [t]


def test_large_table_split_on_rows_with_header_repeated():
    t = make_table(80)
    pieces = split_table(t, 120, count)
    assert len(pieces) > 1
    for p in pieces:
        lines = p.split("\n")
        assert lines[0] == "| Item | Price |" and lines[1] == "| --- | --- |"
        assert count(p) <= 120 + 10
        assert all(ln.startswith("|") and ln.endswith("|") for ln in lines)  # no cut rows
    all_rows = [ln for p in pieces for ln in p.split("\n")[2:]]
    assert all_rows == t.split("\n")[2:]  # nothing lost or duplicated


# ── structure-aware chunker ──────────────────────────────────────────────────

def doc_with(elements: list[DocumentElement]) -> ParsedDocument:
    return ParsedDocument(title="T", pages=[ParsedPage(page_number=1, elements=elements)])


def test_table_is_its_own_chunk_with_hierarchy():
    parsed = doc_with([
        DocumentElement(type="heading", content="Pricing", level=1),
        DocumentElement(type="paragraph", content="Prices are listed below."),
        DocumentElement(type="table", content=make_table(3)),
        DocumentElement(type="paragraph", content="All prices exclude tax."),
    ])
    chunks = StructureAwareChunker().chunk(parsed, 500, 50)
    assert [c.metadata.get("content_type") for c in chunks] == [None, "table", None]
    assert chunks[1].content.startswith("# Pricing")
    assert "| item-0 | $0.00 |" in chunks[1].content
    assert "| item-0" not in chunks[0].content and "| item-0" not in chunks[2].content
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_oversized_table_chunks_keep_header():
    parsed = doc_with([
        DocumentElement(type="heading", content="Prices", level=1),
        DocumentElement(type="table", content=make_table(80)),
    ])
    chunks = StructureAwareChunker().chunk(parsed, 150, 0)
    assert len(chunks) > 1
    for c in chunks:
        assert "| Item | Price |" in c.content and c.metadata["content_type"] == "table"


def test_vision_derived_content_is_marked_in_chunk_metadata():
    parsed = doc_with([
        DocumentElement(type="heading", content="Scan", level=1),
        DocumentElement(
            type="paragraph", content="ocr text", metadata={"derived_from": "vision_ocr"}
        ),
    ])
    chunks = StructureAwareChunker().chunk(parsed, 500, 0)
    assert chunks[0].metadata["derived_from"] == ["vision_ocr"]


# ── transcription parsing ────────────────────────────────────────────────────

def test_transcription_to_elements():
    text = "# Title\n\nFirst line\nsecond line\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n## Sub"
    els = _transcription_to_elements(text, 3)
    assert [(e.type, e.level) for e in els] == [
        ("heading", 1), ("paragraph", None), ("table", None), ("heading", 2)
    ]
    assert els[1].content == "First line second line"
    assert all(e.metadata["derived_from"] == "vision_ocr" and e.page_number == 3 for e in els)


# ── PDF parser ───────────────────────────────────────────────────────────────

def scanned_pdf_bytes() -> bytes:
    """A PDF whose only page content is an image (no text layer)."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 300), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(50, 50, 350, 350), stream=pix.tobytes("png"))
    return doc.tobytes()


def figure_pdf_bytes() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 300), False)
    pix.set_rect(pix.irect, (10, 120, 200))
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quarterly results overview. " * 5, fontsize=11)
    page.insert_image(fitz.Rect(72, 150, 372, 450), stream=pix.tobytes("png"))
    return doc.tobytes()


def table_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Fee schedule", fontsize=11)
    x0, y0, cw, rh = 72, 100, 120, 24
    rows = [["Plan", "Price"], ["Basic", "$10"], ["Pro", "$25"]]
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            rect = fitz.Rect(x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 6, rect.y0 + 16), val, fontsize=11)
    return doc.tobytes()


@pytest.mark.asyncio
async def test_pdf_tables_extracted_as_table_elements():
    parsed = await PDFParser().parse(table_pdf_bytes(), "fees.pdf")
    els = parsed.all_elements()
    tables = [e for e in els if e.type == "table"]
    assert len(tables) == 1
    assert "| Plan | Price |" in tables[0].content and "| Pro | $25 |" in tables[0].content
    # cell text must not be duplicated as loose paragraphs
    assert not any(e.type == "paragraph" and "Basic" in e.content for e in els)


@pytest.mark.asyncio
async def test_scanned_pdf_without_vision_is_flagged_not_ocrd():
    with patch.object(settings, "ENABLE_VISION_INGESTION", False):
        parsed = await PDFParser().parse(scanned_pdf_bytes(), "scan.pdf")
    assert parsed.metadata["scanned_pages"] == 1
    assert parsed.all_elements() == []


@pytest.mark.asyncio
async def test_scanned_pdf_with_vision_is_ocrd():
    fake = AsyncMock(return_value=VisionResult(
        text="# Invoice\n\nTotal due: $42", prompt_tokens=800, completion_tokens=20, model="gpt-4o"
    ))
    with (
        patch.object(settings, "ENABLE_VISION_INGESTION", True),
        patch("app.domains.ingestion.parsers.pdf_parser.describe_image", new=fake),
    ):
        parsed = await PDFParser().parse(scanned_pdf_bytes(), "scan.pdf")

    assert fake.await_args.args[1] == "ocr"
    els = parsed.all_elements()
    assert [e.type for e in els] == ["heading", "paragraph"]
    assert els[1].metadata["derived_from"] == "vision_ocr"
    assert parsed.metadata["vision_calls"] == 1
    assert parsed.metadata["vision_prompt_tokens"] == 800


@pytest.mark.asyncio
async def test_figures_described_when_vision_enabled():
    fake = AsyncMock(return_value=VisionResult(text="Bar chart of revenue", model="gpt-4o"))
    with (
        patch.object(settings, "ENABLE_VISION_INGESTION", True),
        patch("app.domains.ingestion.parsers.pdf_parser.describe_image", new=fake),
    ):
        parsed = await PDFParser().parse(figure_pdf_bytes(), "report.pdf")

    assert fake.await_args.args[1] == "figure"
    captions = [e for e in parsed.all_elements() if e.type == "image_caption"]
    assert len(captions) == 1
    assert "Bar chart of revenue" in captions[0].content
    assert captions[0].metadata["derived_from"] == "vision_figure"


@pytest.mark.asyncio
async def test_vision_failure_does_not_fail_parsing():
    with (
        patch.object(settings, "ENABLE_VISION_INGESTION", True),
        patch(
            "app.domains.ingestion.parsers.pdf_parser.describe_image",
            new=AsyncMock(return_value=None),
        ),
    ):
        parsed = await PDFParser().parse(figure_pdf_bytes(), "report.pdf")
    assert parsed.metadata["vision_calls"] == 0
    assert any(e.type == "paragraph" for e in parsed.all_elements())


@pytest.mark.asyncio
async def test_vision_call_cap_prioritises_ocr_and_counts_skipped():
    fake = AsyncMock(return_value=VisionResult(text="x", model="gpt-4o"))
    with (
        patch.object(settings, "ENABLE_VISION_INGESTION", True),
        patch.object(settings, "MAX_VISION_CALLS_PER_DOC", 1),
        patch("app.domains.ingestion.parsers.pdf_parser.describe_image", new=fake),
    ):
        pages = [ParsedPage(page_number=1, elements=[]), ParsedPage(page_number=2, elements=[])]
        meta = await PDFParser()._apply_vision(pages, [(1, b"a")], [(2, b"b")])
    assert fake.await_count == 1 and fake.await_args.args[1] == "ocr"
    assert meta["vision_skipped_over_cap"] == 1
