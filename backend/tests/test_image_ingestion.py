import pymupdf as fitz
import pytest

from app.config import settings
from app.core.exceptions import IngestionError, ValidationError
from app.domains.documents.upload_safety import sniff_content
from app.domains.ingestion.parsers import ImageParser, get_parser
from app.domains.ingestion.parsers import image_parser as image_parser_module
from app.domains.ingestion.parsers.image_parser import MAX_LONG_EDGE, normalize_image
from app.models.document import FileType
from app.providers.ocr.base import OCRProvider, OCRResult
from app.providers.ocr.registry import get_ocr_provider
from app.providers.ocr.vision_ocr import VisionOCRProvider


def make_png(width=40, height=30, n=3, alpha=False) -> bytes:
    cs = {1: fitz.csGRAY, 3: fitz.csRGB}[n]
    pix = fitz.Pixmap(cs, fitz.IRect(0, 0, width, height), alpha)
    pix.clear_with(200)
    return pix.tobytes("png")


class FakeOCR(OCRProvider):
    def __init__(self, text="# Invoice\n\nTotal due: 120 USD\n\n| Item | Cost |\n| --- | --- |\n| A | 120 |"):
        self.text, self.seen = text, []

    async def read(self, image_png: bytes):
        self.seen.append(image_png)
        return OCRResult(text=self.text, prompt_tokens=100, completion_tokens=40, model="vis") if self.text else None


@pytest.fixture
def ocr(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_VISION_INGESTION", True)
    fake = FakeOCR()
    monkeypatch.setattr(image_parser_module, "get_ocr_provider", lambda: fake)
    return fake


def test_image_parser_registered_and_ocr_registry():
    assert isinstance(get_parser(FileType.image), ImageParser)
    assert isinstance(get_ocr_provider("vision"), VisionOCRProvider)
    with pytest.raises(ValueError, match="OCR_PROVIDER"):
        get_ocr_provider("nope")


@pytest.mark.asyncio
async def test_image_is_ocrd_into_structured_marked_elements(ocr):
    doc = await ImageParser().parse(make_png(), "invoice.png")
    kinds = [(e.type, e.content) for e in doc.all_elements()]
    assert ("heading", "Invoice") in kinds
    assert any(t == "table" and "| A | 120 |" in c for t, c in kinds)
    assert all(e.metadata.get("derived_from") == "vision_ocr" for e in doc.all_elements())
    assert doc.metadata["vision_calls"] == 1 and doc.metadata["vision_prompt_tokens"] == 100
    assert doc.title == "invoice"


@pytest.mark.asyncio
async def test_ocr_receives_normalized_rgb_png_not_the_upload(ocr):
    # Grayscale input is converted to RGB PNG before the model sees it.
    await ImageParser().parse(make_png(n=1), "gray.png")
    sent = ocr.seen[0]
    assert sent.startswith(b"\x89PNG")
    assert fitz.Pixmap(sent).colorspace.n == 3


@pytest.mark.asyncio
async def test_disabled_vision_fails_with_actionable_error(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_VISION_INGESTION", False)
    with pytest.raises(IngestionError, match="ENABLE_VISION_INGESTION"):
        await ImageParser().parse(make_png(), "x.png")


@pytest.mark.asyncio
async def test_unreadable_image_and_empty_ocr_fail_ingestion(ocr, monkeypatch):
    with pytest.raises(IngestionError, match="decode"):
        await ImageParser().parse(b"\x89PNG\r\n\x1a\nnot really a png", "x.png")
    monkeypatch.setattr(image_parser_module, "get_ocr_provider", lambda: FakeOCR(text=""))
    with pytest.raises(IngestionError, match="No text"):
        await ImageParser().parse(make_png(), "blank.png")


def test_decompression_bomb_is_rejected_by_pixel_count(monkeypatch):
    monkeypatch.setattr(image_parser_module, "MAX_PIXELS", 1000)
    with pytest.raises(IngestionError, match="too large"):
        normalize_image(make_png(100, 100))


def test_large_images_are_downscaled():
    out = fitz.Pixmap(normalize_image(make_png(MAX_LONG_EDGE * 2 + 100, 500)))
    assert max(out.width, out.height) < MAX_LONG_EDGE * 2


# --- upload sniffing -----------------------------------------------------------------


def test_sniff_accepts_real_images_and_rejects_others():
    sniff_content(make_png(), FileType.image)
    sniff_content(b"\xff\xd8\xff\xe0" + b"0" * 20, FileType.image)
    sniff_content(b"RIFF\x00\x00\x00\x00WEBPVP8 ", FileType.image)
    for bad in (b"%PDF-1.4", b"GIF89a....", b"MZ\x90\x00", b"<svg onload=alert(1)>"):
        with pytest.raises(ValidationError):
            sniff_content(bad, FileType.image)
