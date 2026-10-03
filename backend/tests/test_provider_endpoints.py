"""OpenAI-compatible endpoints (e.g. OpenRouter) for chat and embeddings."""

import uuid

from app.config import settings
from app.domains.chat.schemas import ChatRequest
from app.domains.rag.schemas import RAGRequest
from app.providers import cost
from app.providers.embeddings import openai_embeddings
from app.providers.llm import openai_provider
from app.providers.llm.registry import get_llm_provider


class Capture:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_llm_client_uses_configured_base_url_and_key(monkeypatch):
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", Capture)
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "LLM_API_KEY", "or-key")
    client = openai_provider.OpenAIProvider(model="vendor/some-model:free")._client
    assert client.kwargs == {"api_key": "or-key", "base_url": "https://openrouter.ai/api/v1"}


def test_llm_client_defaults_to_openai(monkeypatch):
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", Capture)
    monkeypatch.setattr(settings, "LLM_BASE_URL", None)
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "oa-key")
    assert openai_provider.OpenAIProvider()._client.kwargs == {"api_key": "oa-key", "base_url": None}


def test_embeddings_are_configured_independently_of_the_llm(monkeypatch):
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", Capture)
    monkeypatch.setattr(openai_embeddings, "AsyncOpenAI", Capture)
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "LLM_API_KEY", "or-key")
    monkeypatch.setattr(settings, "EMBEDDING_BASE_URL", None)
    monkeypatch.setattr(settings, "EMBEDDING_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "oa-key")
    emb = openai_embeddings.OpenAIEmbeddingProvider()._client
    assert emb.kwargs == {"api_key": "oa-key", "base_url": None}  # stays on OpenAI


def test_request_model_defaults_follow_the_configured_default(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_LLM_MODEL", "vendor/some-model:free")
    assert ChatRequest(message="hi", knowledge_base_ids=[uuid.uuid4()]).model == "vendor/some-model:free"
    assert RAGRequest(query="q", knowledge_base_ids=[uuid.uuid4()]).model == "vendor/some-model:free"
    chosen = ChatRequest(message="hi", knowledge_base_ids=[uuid.uuid4()], model="x/y")
    assert chosen.model == "x/y"


def test_openrouter_style_ids_route_to_the_openai_compatible_client(monkeypatch):
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", Capture)
    assert isinstance(get_llm_provider("meta/llama-3-free:free"), openai_provider.OpenAIProvider)


def test_free_models_cost_nothing():
    assert cost.estimate_llm_cost(10_000, 5_000, "vendor/some-model:free") == 0.0
    assert cost.estimate_llm_cost(1_000_000, 0, "gpt-4o") > 0
