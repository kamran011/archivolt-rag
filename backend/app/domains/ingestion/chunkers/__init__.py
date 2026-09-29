from app.domains.ingestion.chunkers.agentic_chunker import AgenticChunker
from app.domains.ingestion.chunkers.base import BaseChunker
from app.domains.ingestion.chunkers.fixed_chunker import FixedChunker
from app.domains.ingestion.chunkers.semantic_chunker import EmbedFn, SemanticChunker
from app.domains.ingestion.chunkers.structure_aware_chunker import StructureAwareChunker
from app.models.knowledge_base import ChunkStrategy
from app.providers.llm.base import LLMProvider


def get_chunker(
    strategy: ChunkStrategy,
    *,
    embed: EmbedFn | None = None,
    llm: LLMProvider | None = None,
) -> BaseChunker:
    """Build the chunker for a strategy. Semantic needs an embedding function and agentic an
    LLM (both are only used for sections that must be split, never for the whole document)."""
    if strategy == ChunkStrategy.fixed:
        return FixedChunker()
    if strategy == ChunkStrategy.structure_aware:
        return StructureAwareChunker()
    if strategy == ChunkStrategy.semantic:
        if embed is None:
            raise ValueError("The semantic chunker needs an embedding function")
        return SemanticChunker(embed)
    if strategy == ChunkStrategy.agentic:
        if llm is None:
            raise ValueError("The agentic chunker needs an LLM provider")
        return AgenticChunker(llm)
    raise ValueError(f"No chunker registered for strategy: {strategy}")


__all__ = [
    "AgenticChunker",
    "BaseChunker",
    "FixedChunker",
    "SemanticChunker",
    "StructureAwareChunker",
    "get_chunker",
]
