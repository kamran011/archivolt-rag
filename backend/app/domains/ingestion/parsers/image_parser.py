"""Images (screenshots, photos of documents, scans) -> text via an OCR provider.

The image is decoded and re-encoded as PNG here, never passed through as uploaded: that
verifies it really is an image, strips metadata, normalizes exotic colour spaces and lets us
reject decompression bombs by pixel count before any model sees it. Text recovered by a
model is marked `derived_from: vision_ocr` so it can be treated as machine-transcribed.
"""

import pymupdf as fitz

from app.config import settings
from app.core.exceptions import IngestionError
from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.parsers.pdf_parser import _transcription_to_elements
from app.domains.ingestion.schemas import ParsedDocument, ParsedPage
from app.providers.ocr.registry import get_ocr_provider

MAX_PIXELS = 50_000_000  # ~7000x7000
MAX_LONG_EDGE = 3000  # larger images are downscaled; vision models don't use more detail


def normalize_image(content: bytes) -> bytes:
    """Decode arbitrary image bytes and return PNG, or raise IngestionError."""
    try:
        pix = fitz.Pixmap(content)
    except Exception as e:
        raise IngestionError(f"Failed to decode image: {e}") from e

    if pix.width * pix.height > MAX_PIXELS:
        raise IngestionError(
            f"Image is too large ({pix.width}x{pix.height}); the limit is {MAX_PIXELS:,} pixels"
        )
    if pix.colorspace is None or pix.colorspace.n != 3 or pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)  # CMYK/gray/alpha -> RGB
    long_edge = max(pix.width, pix.height)
    if long_edge > MAX_LONG_EDGE:
        # shrink(n) halves n times; take as many halvings as keep the long edge >= 60% of
        # the target (coarse but cheap and deterministic).
        halvings = 0
        while long_edge / (2 ** (halvings + 1)) >= MAX_LONG_EDGE * 0.6:
            halvings += 1
        if halvings:
            pix.shrink(halvings)
    return pix.tobytes("png")


class ImageParser(BaseParser):
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        if not settings.ENABLE_VISION_INGESTION:
            raise IngestionError(
                "Image ingestion needs OCR, which is disabled (set ENABLE_VISION_INGESTION=true)"
            )

        png = normalize_image(content)
        result = await get_ocr_provider().read(png)
        if result is None or not result.text.strip():
            raise IngestionError("No text could be read from the image")

        elements = _transcription_to_elements(result.text, 1)
        if not elements:
            raise IngestionError("No text could be read from the image")

        return ParsedDocument(
            title=file_name.rsplit(".", 1)[0],
            pages=[ParsedPage(page_number=1, elements=elements)],
            metadata={
                "source": "image",
                "vision_calls": 1,
                "vision_model": result.model or settings.VISION_MODEL,
                "vision_prompt_tokens": result.prompt_tokens,
                "vision_completion_tokens": result.completion_tokens,
            },
        )
