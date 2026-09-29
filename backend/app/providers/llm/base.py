from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel


class LLMResponse(BaseModel):
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    finish_reason: str


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # pragma: no cover — makes this an async generator for the ABC
