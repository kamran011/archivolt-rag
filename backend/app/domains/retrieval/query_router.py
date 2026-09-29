"""
Adaptive retrieval router: deterministic, rule-based query classification.

Rule-based on purpose — routing must be free, fast and predictable. It picks
a retrieval strategy; the evidence gate still decides whether the result is
good enough to answer from.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

RouteStrategy = Literal["semantic", "keyword", "hybrid", "tree"]

_BROAD_RE = re.compile(
    r"\b(summari[sz]e|summary|overview|outline|what is (this|the) (document|policy|report|"
    r"contract|guide) about|main (points|topics|themes)|key takeaways|table of contents)\b",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r'"[^"]{2,}"')
_IDENTIFIER_RE = re.compile(
    r"\b(?:[A-Z]{2,}[-_]?\d+[\w-]*|\d{2,}[-/.]\d+[\w./-]*|section\s+\d+(?:\.\d+)*|"
    r"clause\s+\d+(?:\.\d+)*|article\s+\d+|§\s*\d+)",
    re.IGNORECASE,
)
_CONCEPTUAL_RE = re.compile(r"^(why|how come|explain|what does .* mean)\b", re.IGNORECASE)


class RouteDecision(BaseModel):
    strategy: RouteStrategy
    reason: str


class QueryRouter:
    @staticmethod
    def route(query: str, *, tree_available: bool = True) -> RouteDecision:
        q = query.strip()

        if _BROAD_RE.search(q):
            if tree_available:
                return RouteDecision(strategy="tree", reason="broad/overview question")
            return RouteDecision(strategy="hybrid", reason="broad question, no document tree")

        if _QUOTED_RE.search(q) or _IDENTIFIER_RE.search(q):
            return RouteDecision(
                strategy="keyword", reason="exact phrase or identifier lookup"
            )

        if _CONCEPTUAL_RE.search(q) and len(q.split()) >= 5:
            return RouteDecision(strategy="semantic", reason="conceptual question")

        return RouteDecision(strategy="hybrid", reason="default")


query_router = QueryRouter()
