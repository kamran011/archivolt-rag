from dataclasses import dataclass

import structlog

from app.config import settings
from app.domains.rag.prompts import CONVERSATION_SUMMARY_PROMPT
from app.providers.llm.base import LLMProvider

logger = structlog.get_logger()

MAX_SUMMARY_CHARS = 2000
MAX_TURN_CHARS = 1500


@dataclass
class ChatMemory:
    recent: list[dict]
    summary: str | None
    summarized_count: int


def _format_turns(turns: list[dict]) -> str:
    return "\n".join(f"{t['role']}: {t['content'][:MAX_TURN_CHARS]}" for t in turns)


async def summarize_turns(
    previous: str | None, turns: list[dict], llm: LLMProvider
) -> str | None:
    """Fold `turns` into the running summary. None on failure (the caller keeps the old one)."""
    prompt = CONVERSATION_SUMMARY_PROMPT.format(
        summary=previous or "(none yet)", messages=_format_turns(turns)
    )
    try:
        response = await llm.generate(
            [{"role": "user", "content": prompt}], temperature=0, max_tokens=400
        )
    except Exception as e:
        logger.warning("history_summary_failed", error=str(e))
        return None
    text = response.content.strip()
    return text[:MAX_SUMMARY_CHARS] or None


async def build_memory(
    turns: list[dict],
    summary: str | None,
    summarized_count: int,
    llm: LLMProvider | None,
    *,
    window: int | None = None,
    batch: int | None = None,
) -> ChatMemory:
    """Summary + buffer: everything after the summary goes verbatim, until enough turns sit
    past the window to fold them in one call. The verbatim part therefore ranges from
    `window` to `window + batch - 1` turns, and no turn falls between summary and buffer."""
    window = window or settings.CHAT_HISTORY_WINDOW
    batch = batch or settings.CHAT_SUMMARY_BATCH
    # A count past the end (messages removed) means the summary no longer lines up: start over.
    if summarized_count > len(turns) or summarized_count <= 0:
        summary, summarized_count = None, 0

    if llm is None:
        return ChatMemory(turns[-window:], None, 0)

    older_end = max(0, len(turns) - window)
    if older_end - summarized_count >= batch:
        folded = await summarize_turns(summary, turns[summarized_count:older_end], llm)
        if folded:
            summary, summarized_count = folded, older_end

    # If folding keeps failing, still bound the prompt.
    start = max(summarized_count, len(turns) - window - batch)
    return ChatMemory(turns[start:], summary, summarized_count)
