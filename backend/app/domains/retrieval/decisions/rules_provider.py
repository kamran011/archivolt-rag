"""Rules-based DecisionProvider - the only provider in V1. Wraps the
existing lexical-coverage `evaluate_sufficiency` function unchanged, so
behavior is identical to pre-abstraction V1; this is purely a seam for V2
to add LLM/Jev providers behind.
"""

from __future__ import annotations

from app.domains.retrieval.analyzer import QueryAnalysis
from app.domains.retrieval.decisions.base import DecisionProvider
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.retrieval.sufficiency import SufficiencyResult, evaluate_sufficiency


class RulesDecisionProvider(DecisionProvider):
    async def evaluate_sufficiency(
        self,
        analysis: QueryAnalysis,
        chunks: list[RetrievedChunk],
        *,
        min_coverage: float | None = None,
        high_confidence: float | None = None,
    ) -> SufficiencyResult:
        # Synchronous and pure (no I/O), so no need to offload to a thread.
        return evaluate_sufficiency(
            analysis, chunks, min_coverage=min_coverage, high_confidence=high_confidence
        )
