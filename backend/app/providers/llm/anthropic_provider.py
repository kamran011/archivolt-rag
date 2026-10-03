from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from app.config import settings
from app.core.exceptions import provider_error
from app.providers.llm.base import LLMProvider, LLMResponse


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    def _split_system(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Anthropic takes the system prompt as a separate top-level param."""
        system = None
        rest = []
        for m in messages:
            if m["role"] == "system" and system is None:
                system = m["content"]
            else:
                rest.append(m)
        return system, rest

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        system, rest = self._split_system(messages)
        try:
            response = await self._client.messages.create(
                model=self.model,
                system=system or "",
                messages=rest,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise provider_error("Anthropic", "generation", e) from e

        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResponse(
            content=text,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            model=response.model,
            finish_reason=response.stop_reason or "end_turn",
        )

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        system, rest = self._split_system(messages)
        try:
            async with self._client.messages.stream(
                model=self.model,
                system=system or "",
                messages=rest,
                temperature=temperature,
                max_tokens=max_tokens,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            raise provider_error("Anthropic", "streaming", e) from e
