from app.config import settings
from app.providers.web_search.base import WebSearchProvider
from app.providers.web_search.brave import BraveSearchProvider


class NoWebSearch(WebSearchProvider):
    @property
    def configured(self) -> bool:
        return False

    async def search(self, query, max_results):
        raise RuntimeError("web search is not configured")


def get_web_search_provider(name: str | None = None) -> WebSearchProvider:
    provider = (name or settings.WEB_SEARCH_PROVIDER).lower()
    if provider == "brave":
        return BraveSearchProvider()
    if provider == "none":
        return NoWebSearch()
    raise ValueError(f"Unknown WEB_SEARCH_PROVIDER '{provider}' (expected brave or none)")
