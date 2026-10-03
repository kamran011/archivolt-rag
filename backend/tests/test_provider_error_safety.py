import pytest

from app.core.exceptions import ProviderError, provider_error

LEAKY_BODY = (
    "Error code: 401 - {'error': {'message': 'Incorrect API key provided: "
    "sk-proj-********************wxyz. You can find your API key at ...'}}"
)


class FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int | None) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "rejected the server's API credentials"),
        (403, "rejected the server's API credentials"),
        (429, "rate limit or quota"),
        (503, "temporarily unavailable"),
        (None, "unexpected provider error"),
    ],
)
def test_provider_error_is_classified_and_never_echoes_the_raw_body(status, expected):
    err = provider_error("OpenAI", "embedding", FakeAPIError(LEAKY_BODY, status))
    assert isinstance(err, ProviderError)
    assert expected in str(err)
    assert "sk-" not in str(err) and "wxyz" not in str(err) and "Incorrect API key" not in str(err)


@pytest.mark.asyncio
async def test_embedding_provider_failure_message_is_safe(monkeypatch):
    from app.providers.embeddings import openai_embeddings as mod

    monkeypatch.setattr(mod.asyncio, "sleep", lambda *_: _noop())
    provider = mod.OpenAIEmbeddingProvider()

    class Boom:
        class embeddings:  # noqa: N801
            @staticmethod
            async def create(**kwargs):
                raise mod.APIError(LEAKY_BODY, request=None, body=None)

    provider._client = Boom()
    with pytest.raises(ProviderError) as exc:
        await provider.embed_texts(["hello"])
    assert "sk-" not in str(exc.value) and "wxyz" not in str(exc.value)


async def _noop():
    return None
