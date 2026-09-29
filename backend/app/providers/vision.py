import base64
from typing import Literal

import structlog
from pydantic import BaseModel

from app.config import settings
from app.providers.llm.registry import get_llm_provider

logger = structlog.get_logger()

VisionMode = Literal["ocr", "figure"]

_PROMPTS: dict[VisionMode, str] = {
    "ocr": (
        "Transcribe all text on this scanned page exactly as written, in reading order. "
        "Use markdown: '#'/'##' for headings, markdown tables for tables. Do not summarize, "
        "correct, or add anything. Mark illegible text as [illegible]. Output only the "
        "transcription."
    ),
    "figure": (
        "This is a figure from a document. In 2-4 sentences, state what kind of figure it is "
        "and what it shows, then list any visible labels, axis titles, legend entries and "
        "numeric values exactly as shown. Do not infer facts that are not visible. Output "
        "only the description."
    ),
}


class VisionResult(BaseModel):
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str


async def describe_image(image_png: bytes, mode: VisionMode) -> VisionResult | None:
    """Sends one image to the vision model. Returns None on failure — image
    understanding is enrichment, so a failed call must not fail ingestion."""
    data_uri = "data:image/png;base64," + base64.b64encode(image_png).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPTS[mode]},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
    ]
    try:
        llm = get_llm_provider(settings.VISION_MODEL)
        resp = await llm.generate(messages, temperature=0.0, max_tokens=2048)
    except Exception as e:
        logger.warning("vision_call_failed", mode=mode, error=str(e))
        return None

    text = resp.content.strip()
    if not text:
        return None
    return VisionResult(
        text=text,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
        model=settings.VISION_MODEL,
    )
