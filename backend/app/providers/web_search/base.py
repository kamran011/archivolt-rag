from abc import ABC, abstractmethod

from pydantic import BaseModel


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str


class WebSearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int) -> list[WebResult]:
        """Search the public web. Only the query leaves the system: no documents, no
        identifiers. Raises on transport/HTTP errors (callers handle failure)."""
        raise NotImplementedError

    @property
    def configured(self) -> bool:
        return True
