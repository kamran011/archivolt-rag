import re
from abc import ABC, abstractmethod

import tiktoken

from app.domains.ingestion.schemas import ChunkData, ParsedDocument

_encoding = tiktoken.get_encoding("cl100k_base")

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class BaseChunker(ABC):
    @abstractmethod
    def chunk(
        self,
        parsed: ParsedDocument,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkData]:
        raise NotImplementedError

    async def achunk(
        self,
        parsed: ParsedDocument,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkData]:
        """Async entry point used by ingestion. Chunkers that need embeddings or an LLM
        override this; the rest just run synchronously."""
        return self.chunk(parsed, chunk_size, chunk_overlap)

    def count_tokens(self, text: str) -> int:
        return len(_encoding.encode(text))

    def split_sentences(self, text: str) -> list[str]:
        return [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
