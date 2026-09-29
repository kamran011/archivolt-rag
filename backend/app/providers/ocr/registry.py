from app.config import settings
from app.providers.ocr.base import OCRProvider
from app.providers.ocr.vision_ocr import VisionOCRProvider


def get_ocr_provider(name: str | None = None) -> OCRProvider:
    provider = (name or settings.OCR_PROVIDER).lower()
    if provider == "vision":
        return VisionOCRProvider()
    raise ValueError(f"Unknown OCR_PROVIDER '{provider}' (expected: vision)")
