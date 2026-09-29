from abc import ABC, abstractmethod

from app.domains.ingestion.schemas import ParsedDocument


class BaseParser(ABC):
    @abstractmethod
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        """Parse raw file bytes into a structured document representation."""
        raise NotImplementedError
