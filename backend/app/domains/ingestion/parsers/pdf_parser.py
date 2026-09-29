import asyncio

import pymupdf as fitz
import structlog

from app.config import settings
from app.core.exceptions import IngestionError
from app.domains.ingestion.chunkers.table import rows_to_markdown
from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage
from app.providers.vision import VisionMode, VisionResult, describe_image

logger = structlog.get_logger()

# Heuristic thresholds for heading detection by font size relative to body text
HEADING_SIZE_RATIO = 1.15
VISION_CONCURRENCY = 3
OCR_DPI = 150


class PDFParser(BaseParser):
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            raise IngestionError(f"Failed to open PDF: {e}")

        try:
            body_size = self._estimate_body_font_size(doc)
            pages: list[ParsedPage] = []
            ocr_jobs: list[tuple[int, bytes]] = []
            figure_jobs: list[tuple[int, bytes]] = []
            scanned_pages = 0
            seen_xrefs: set[int] = set()

            for page_num, page in enumerate(doc, start=1):
                elements = self._extract_page_elements(page, body_size, page_num)
                pages.append(ParsedPage(page_number=page_num, elements=elements))

                text_chars = sum(len(e.content) for e in elements if e.type != "table")
                images = page.get_images(full=True)
                if not images:
                    continue

                if text_chars < settings.SCANNED_PAGE_MIN_CHARS:
                    scanned_pages += 1
                    if settings.ENABLE_VISION_INGESTION:
                        ocr_jobs.append(
                            (page_num, page.get_pixmap(dpi=OCR_DPI).tobytes("png"))
                        )
                elif settings.ENABLE_VISION_INGESTION:
                    for png in self._figure_pngs(doc, images, seen_xrefs):
                        figure_jobs.append((page_num, png))

            metadata: dict = {"page_count": len(doc), "source": "pdf"}
            if scanned_pages:
                metadata["scanned_pages"] = scanned_pages
            if settings.ENABLE_VISION_INGESTION:
                metadata.update(await self._apply_vision(pages, ocr_jobs, figure_jobs))

            title = doc.metadata.get("title") or file_name.rsplit(".", 1)[0]
            return ParsedDocument(title=title, pages=pages, metadata=metadata)
        finally:
            doc.close()

    async def _apply_vision(
        self,
        pages: list[ParsedPage],
        ocr_jobs: list[tuple[int, bytes]],
        figure_jobs: list[tuple[int, bytes]],
    ) -> dict:
        # OCR of scanned pages is prioritised over figure descriptions when capped.
        jobs: list[tuple[VisionMode, int, bytes]] = [
            ("ocr", n, png) for n, png in ocr_jobs
        ] + [("figure", n, png) for n, png in figure_jobs]
        cap = settings.MAX_VISION_CALLS_PER_DOC
        skipped = max(0, len(jobs) - cap)
        jobs = jobs[:cap]

        sem = asyncio.Semaphore(VISION_CONCURRENCY)

        async def run(mode: VisionMode, png: bytes) -> VisionResult | None:
            async with sem:
                return await describe_image(png, mode)

        results = await asyncio.gather(*(run(m, png) for m, _, png in jobs))

        by_page = {p.page_number: p for p in pages}
        prompt_tokens = completion_tokens = calls = 0
        for (mode, page_num, _), result in zip(jobs, results, strict=True):
            if result is None:
                continue
            calls += 1
            prompt_tokens += result.prompt_tokens
            completion_tokens += result.completion_tokens
            page = by_page[page_num]
            if mode == "ocr":
                page.elements = _transcription_to_elements(result.text, page_num)
            else:
                page.elements.append(
                    DocumentElement(
                        type="image_caption",
                        content=f"[Figure on page {page_num}] {result.text}",
                        page_number=page_num,
                        metadata={"derived_from": "vision_figure"},
                    )
                )

        return {
            "vision_calls": calls,
            "vision_model": settings.VISION_MODEL,
            "vision_prompt_tokens": prompt_tokens,
            "vision_completion_tokens": completion_tokens,
            "vision_skipped_over_cap": skipped,
        }

    def _figure_pngs(
        self, doc: "fitz.Document", images: list, seen_xrefs: set[int]
    ) -> list[bytes]:
        pngs: list[bytes] = []
        for img in images:
            xref, width, height = img[0], img[2], img[3]
            if xref in seen_xrefs:
                continue
            if min(width, height) < settings.MIN_FIGURE_PIXELS:
                continue
            seen_xrefs.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pngs.append(pix.tobytes("png"))
            except Exception as e:
                logger.warning("figure_extract_failed", xref=xref, error=str(e))
        return pngs

    def _estimate_body_font_size(self, doc: "fitz.Document") -> float:
        sizes: dict[float, int] = {}
        for page in doc:
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = round(span.get("size", 0), 1)
                        text_len = len(span.get("text", "").strip())
                        if text_len > 0:
                            sizes[size] = sizes.get(size, 0) + text_len
        if not sizes:
            return 10.0
        return max(sizes, key=lambda s: sizes[s])

    def _extract_tables(self, page: "fitz.Page") -> list[tuple[tuple[float, ...], str]]:
        try:
            found = page.find_tables()
            tables = []
            for t in found.tables:
                md = rows_to_markdown(t.extract())
                if md:
                    tables.append((tuple(t.bbox), md))
            return tables
        except Exception as e:  # table detection is best-effort
            logger.warning("table_detection_failed", error=str(e))
            return []

    def _extract_page_elements(
        self, page: "fitz.Page", body_size: float, page_num: int
    ) -> list[DocumentElement]:
        tables = self._extract_tables(page)
        items: list[tuple[float, DocumentElement]] = []
        text_dict = page.get_text("dict")

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # skip non-text blocks (images)
                continue

            x0, y0, x1, y1 = block.get("bbox", (0, 0, 0, 0))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if any(tx0 <= cx <= tx1 and ty0 <= cy <= ty1 for (tx0, ty0, tx1, ty1), _ in tables):
                continue  # text already captured inside a table

            block_text_parts = []
            max_size = 0.0
            is_bold = False

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    block_text_parts.append(text)
                    size = span.get("size", 0)
                    if size > max_size:
                        max_size = size
                    flags = span.get("flags", 0)
                    if flags & 2**4:  # bold flag
                        is_bold = True

            block_text = "".join(block_text_parts).strip()
            if not block_text:
                continue

            if max_size >= body_size * HEADING_SIZE_RATIO or (is_bold and max_size > body_size):
                level = 1 if max_size >= body_size * 1.4 else 2
                el = DocumentElement(
                    type="heading", content=block_text, level=level, page_number=page_num
                )
            else:
                el = DocumentElement(type="paragraph", content=block_text, page_number=page_num)
            items.append((y0, el))

        for (_, ty0, _, _), md in sorted(tables, key=lambda t: t[0][1]):
            table_el = DocumentElement(type="table", content=md, page_number=page_num)
            pos = next((i for i, (y, _) in enumerate(items) if y > ty0), len(items))
            items.insert(pos, (ty0, table_el))

        return [el for _, el in items]


def _transcription_to_elements(text: str, page_num: int) -> list[DocumentElement]:
    """Turns a vision-model markdown transcription into structured elements."""
    meta = {"derived_from": "vision_ocr"}
    elements: list[DocumentElement] = []
    paragraph: list[str] = []
    table: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            elements.append(
                DocumentElement(
                    type="paragraph", content=" ".join(paragraph), page_number=page_num,
                    metadata=dict(meta),
                )
            )
            paragraph.clear()

    def flush_table() -> None:
        if table:
            elements.append(
                DocumentElement(
                    type="table", content="\n".join(table), page_number=page_num,
                    metadata=dict(meta),
                )
            )
            table.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_table()
        elif line.startswith("|"):
            flush_paragraph()
            table.append(line)
        elif line.startswith("#"):
            flush_paragraph()
            flush_table()
            level = min(len(line) - len(line.lstrip("#")), 6)
            elements.append(
                DocumentElement(
                    type="heading", content=line.lstrip("#").strip(), level=level,
                    page_number=page_num, metadata=dict(meta),
                )
            )
        else:
            flush_table()
            paragraph.append(line)
    flush_paragraph()
    flush_table()
    return elements
