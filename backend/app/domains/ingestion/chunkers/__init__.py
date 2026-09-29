from app.domains.ingestion.chunkers.base import BaseChunker
from app.domains.ingestion.chunkers.fixed_chunker import FixedChunker
from app.domains.ingestion.chunkers.structure_aware_chunker import StructureAwareChunker
from app.models.knowledge_base import ChunkStrategy

_REGISTRY: dict[ChunkStrategy, type[BaseChunker]] = {
    ChunkStrategy.fixed: FixedChunker,
    ChunkStrategy.structure_aware: StructureAwareChunker,
}


def get_chunker(strategy: ChunkStrategy) -> BaseChunker:
    chunker_cls = _REGISTRY.get(strategy)
    if not chunker_cls:
        raise ValueError(f"No chunker registered for strategy: {strategy}")
    return chunker_cls()


__all__ = ["BaseChunker", "FixedChunker", "StructureAwareChunker", "get_chunker"]
