from abc import ABC, abstractmethod

from pydantic import BaseModel


class OCRResult(BaseModel):
    text: str  # markdown transcription (headings '#', tables '|')
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class OCRProvider(ABC):
    @abstractmethod
    async def read(self, image_png: bytes) -> OCRResult | None:
        """Transcribe text from a PNG image. Return None when nothing could be read."""
        raise NotImplementedError
