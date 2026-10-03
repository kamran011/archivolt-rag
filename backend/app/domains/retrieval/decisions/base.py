"""DecisionProvider: the pluggable seam for "is this evidence enough?" and
other retrieval decisions.

V1 ships a single rules-based implementation (`RulesDecisionProvider`,
wrapping the existing lexical-coverage logic in `retrieval/sufficiency.py`
unchanged). V2 adds LLM- and Jev-backed providers behind the same
interface - callers depend on `DecisionProvider`, never on a concrete
implementation, so a new provider is a registry entry, not a call-site
change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domains.retrieval.analyzer import QueryAnalysis
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.retrieval.sufficiency import SufficiencyResult


class DecisionProvider(ABC):
    @abstractmethod
    async def evaluate_sufficiency(
        self,
        analysis: QueryAnalysis,
        chunks: list[RetrievedChunk],
        *,
        min_coverage: float | None = None,
        high_confidence: float | None = None,
    ) -> SufficiencyResult:
        raise NotImplementedError
