from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.config import settings
from app.core.exceptions import provider_error
from app.providers.llm.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.DEFAULT_LLM_MODEL
        self._client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY or settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise provider_error("OpenAI", "generation", e) from e

        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            model=response.model,
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            raise provider_error("OpenAI", "streaming", e) from e
