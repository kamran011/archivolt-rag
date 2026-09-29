from app.providers.llm.anthropic_provider import AnthropicProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.openai_provider import OpenAIProvider


def get_llm_provider(model: str) -> LLMProvider:
    if model.startswith("claude"):
        return AnthropicProvider(model=model)
    return OpenAIProvider(model=model)
