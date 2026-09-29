import httpx

from app.config import settings
from app.providers.web_search.base import WebResult, WebSearchProvider

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider(WebSearchProvider):
    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.BRAVE_API_KEY
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, max_results: int) -> list[WebResult]:
        if not self._api_key:
            raise RuntimeError("BRAVE_API_KEY is not set")
        params = {"q": query, "count": max(1, min(max_results, 10)), "safesearch": "moderate"}
        headers = {"X-Subscription-Token": self._api_key, "Accept": "application/json"}
        if self._client is not None:
            response = await self._client.get(BRAVE_URL, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(BRAVE_URL, params=params, headers=headers)
        response.raise_for_status()
        results = (response.json().get("web") or {}).get("results") or []
        return [
            WebResult(
                title=str(r.get("title") or "")[:300],
                url=str(r.get("url") or ""),
                snippet=str(r.get("description") or "")[:1500],
            )
            for r in results
            if r.get("url")
        ][:max_results]
