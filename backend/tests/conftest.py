import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class _NoNetwork:
    """Stands in for the OpenAI/Anthropic SDK clients: any real call fails immediately.

    Tests must stub the provider they exercise. Without this guard an unstubbed call
    (say, tree navigation in a retrieval fallback) tries the real API with a fake key:
    slow, flaky, and a pointless outbound request from a test run."""

    def __getattr__(self, name):
        return self

    async def create(self, *args, **kwargs):
        raise RuntimeError("real network access is disabled in tests; stub the provider")

    def stream(self, *args, **kwargs):
        raise RuntimeError("real network access is disabled in tests; stub the provider")


@pytest.fixture(autouse=True)
def _no_real_llm_network(monkeypatch):
    factory = lambda *args, **kwargs: _NoNetwork()  # noqa: E731
    monkeypatch.setattr("app.providers.llm.openai_provider.AsyncOpenAI", factory)
    monkeypatch.setattr("app.providers.llm.anthropic_provider.AsyncAnthropic", factory)
    monkeypatch.setattr("app.providers.embeddings.openai_embeddings.AsyncOpenAI", factory)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
