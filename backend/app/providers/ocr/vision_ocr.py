from app.providers.ocr.base import OCRProvider, OCRResult
from app.providers.vision import describe_image


class VisionOCRProvider(OCRProvider):
    """OCR through the configured vision-capable LLM (see providers/vision.py)."""

    async def read(self, image_png: bytes) -> OCRResult | None:
        result = await describe_image(image_png, "ocr")
        if result is None:
            return None
        return OCRResult(
            text=result.text,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            model=result.model,
        )
