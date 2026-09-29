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

    def count_tokens(self, text: str) -> int:
        return len(_encoding.encode(text))

    def split_sentences(self, text: str) -> list[str]:
        return [s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
