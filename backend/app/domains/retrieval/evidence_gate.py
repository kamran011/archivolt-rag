from pydantic import BaseModel

from app.config import settings
from app.domains.retrieval.schemas import RetrievedChunk


class EvidenceGateResult(BaseModel):
    pass_gate: bool
    reason: str | None = None
    confidence: float
    top_score: float
    chunk_count: int


class EvidenceGate:
    @staticmethod
    def evaluate(
        query: str,
        chunks: list[RetrievedChunk],
        min_relevance_threshold: float | None = None,
    ) -> EvidenceGateResult:
        threshold = (
            min_relevance_threshold
            if min_relevance_threshold is not None
            else settings.MIN_RELEVANCE_SCORE
        )

        if not chunks:
            return EvidenceGateResult(
                pass_gate=False,
                reason="No evidence retrieved for this query",
                confidence=0.0,
                top_score=0.0,
                chunk_count=0,
            )

        top_score = max(c.score for c in chunks)

        if top_score < threshold:
            return EvidenceGateResult(
                pass_gate=False,
                reason=f"Top relevance score ({top_score:.2f}) is below the minimum threshold ({threshold:.2f})",
                confidence=top_score,
                top_score=top_score,
                chunk_count=len(chunks),
            )

        return EvidenceGateResult(
            pass_gate=True,
            reason=None,
            confidence=top_score,
            top_score=top_score,
            chunk_count=len(chunks),
        )
