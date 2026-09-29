"""web_search: the one tool that talks to the outside world.

Controls, all of which must hold: ENABLE_WEB_SEARCH (deployment), the organization's admin
opt-in (settings.web_search_enabled) and the user's per-request toggle.

What may leave the system: only the search query. The query is screened first, so neither a
manipulated planner nor a careless question can send internal document text or secrets to a
third party (see `query_violation`). What comes back is untrusted external content: it is
labelled `source=external`, given the lowest authority, never merged into internal evidence
without that label, and passes through the same rerank/filter/gate/verification as anything
else. Nothing returned is ever fetched or executed; URLs are validated http(s) links only.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.tools.base import Tool, ToolContext, ToolResult
from app.providers.web_search.registry import get_web_search_provider

SHINGLE_WORDS = 6
MAX_URL_CHARS = 500
BASE_SCORE = 0.6
RANK_STEP = 0.05

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("a card-like number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("an API key", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}")),
    ("an AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]+-----")),
    ("an ID number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("a token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
]
_WORD_RE = re.compile(r"[a-z0-9]+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _shingles(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def query_violation(query: str, internal_texts: list[str]) -> str | None:
    """Return why this query must not leave the system, or None if it is fine.

    Blocks (1) secrets/PII-shaped strings and (2) anything that quotes a run of
    SHINGLE_WORDS consecutive words from internal evidence gathered in this run."""
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(query):
            return f"the query contains {label}"
    query_shingles = _shingles(_words(query), SHINGLE_WORDS)
    if query_shingles:
        for text in internal_texts:
            if query_shingles & _shingles(_words(text), SHINGLE_WORDS):
                return "the query quotes internal document text"
    return None


def safe_url(url: str) -> str | None:
    """Only plain http(s) links, no credentials, bounded length."""
    if not url or len(url) > MAX_URL_CHARS or any(ord(c) < 33 for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return url


def _clean(text: str) -> str:
    return " ".join(_CONTROL_RE.sub(" ", text).split())


class WebSearchTool(Tool):
    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "search the public web (external, lower-authority source) for current information "
        "that is not in the knowledge base; only the query is sent"
    )
    max_calls_per_run: ClassVar[int] = 2

    class Args(BaseModel):
        query: str = Field(min_length=3, max_length=200)

    def denied_reason(self, ctx: ToolContext) -> str | None:
        if not settings.ENABLE_WEB_SEARCH:
            return "web search is disabled on this deployment"
        if ctx.org_settings.get("web_search_enabled") is not True:
            return "web search is not enabled for this organization"
        if not ctx.web_search_requested:
            return "web search was not requested for this question"
        if not get_web_search_provider().configured:
            return "no web search provider is configured"
        return None

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        query = _clean(args.query)
        violation = query_violation(query, ctx.internal_texts)
        if violation:
            return ToolResult(ok=False, error=f"web_search blocked: {violation}")

        results = await get_web_search_provider().search(query, settings.WEB_SEARCH_MAX_RESULTS)
        chunks: list[RetrievedChunk] = []
        for rank, r in enumerate(results):
            url = safe_url(r.url)
            if url is None:
                continue
            title = _clean(r.title)[:200] or urlsplit(url).hostname or url
            chunks.append(
                RetrievedChunk(
                    chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, url),
                    document_id=uuid.uuid5(uuid.NAMESPACE_URL, url),
                    document_title=title,
                    content=f"{title}. {_clean(r.snippet)}"[:1500],
                    score=max(0.1, BASE_SCORE - RANK_STEP * rank),
                    metadata={
                        "source": "external",
                        "url": url,
                        "derived_from": ["web"],
                        "content_type": "web_result",
                    },
                    retrieval_method="web",
                    is_current=True,
                    authority_tier="draft",  # lowest: internal sources win any conflict
                )
            )
        return ToolResult(content=f"{len(chunks)} external results", chunks=chunks)
