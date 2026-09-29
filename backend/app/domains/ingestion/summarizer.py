import asyncio

import structlog

from app.config import settings
from app.domains.ingestion.schemas import ChunkData
from app.domains.retrieval.tree import TreeNode, iter_nodes
from app.providers.llm.registry import get_llm_provider

logger = structlog.get_logger()

MAX_SUMMARY_INPUT_CHARS = 6000
MAX_CONCURRENCY = 4

SUMMARY_PROMPT = """Summarize this document section in one sentence (max 30 words) so a reader \
can decide whether it is relevant to a question. State what it covers, not conclusions.

Section: {title}

{content}"""


async def summarize_tree(nodes: list[TreeNode], chunks: list[ChunkData]) -> int:
    """Fills TreeNode.summary in place using a cheap model. Summaries are
    navigation aids only and are never returned as evidence. Fail-safe: a
    failed section simply has no summary. Returns the number of summaries."""
    by_index = {c.chunk_index: c.content for c in chunks}
    llm = get_llm_provider(settings.RERANKER_MODEL)
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def one(node: TreeNode) -> bool:
        text = "\n\n".join(by_index[i] for i in node.chunk_indices if i in by_index)
        if not text:
            return False
        async with sem:
            try:
                resp = await llm.generate(
                    [
                        {
                            "role": "user",
                            "content": SUMMARY_PROMPT.format(
                                title=node.title, content=text[:MAX_SUMMARY_INPUT_CHARS]
                            ),
                        }
                    ],
                    temperature=0.0,
                    max_tokens=80,
                )
            except Exception as e:
                logger.warning("section_summary_failed", node=node.title, error=str(e))
                return False
        node.summary = resp.content.strip()
        return True

    results = await asyncio.gather(*(one(n) for n in iter_nodes(nodes)))
    return sum(results)
