import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.domains.retrieval.evidence_gate import EvidenceGateResult


class RAGRequest(BaseModel):
    query: str
    knowledge_base_ids: list[uuid.UUID]
    conversation_history: list[dict] | None = None
    # Summary of turns older than conversation_history; background only, never a source.
    conversation_summary: str | None = None
    model: str = Field(default_factory=lambda: settings.DEFAULT_LLM_MODEL)
    temperature: float = 0.1
    agentic: bool = False
    web_search: bool = False  # the user asked to allow external web results
    # rag: retrieve passages. cag: answer from the whole (small) KB. hybrid: RAG first, then
    # CAG if RAG's evidence is insufficient. CAG needs the KB to opt in and fit the budget.
    mode: Literal["rag", "cag", "hybrid"] = "rag"


class Citation(BaseModel):
    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    page_number: int | None = None
    relevance_score: float
    # 'internal' (the knowledge base) or 'external' (public web); url only for external.
    source_type: str = "internal"
    url: str | None = None


class AbstentionReason(str, Enum):
    """Why the system declined to answer. Abstaining is a valid outcome."""

    insufficient_evidence = "insufficient_evidence"
    conflicting_sources = "conflicting_sources"
    verification_failed = "verification_failed"
    # Reserved: not produced today because retrieval is tenant-scoped up front
    # (unauthorized), superseded docs are filtered out (outdated), and there is
    # no question-type classifier yet (unsupported_question).
    unauthorized = "unauthorized"
    outdated = "outdated"
    unsupported_question = "unsupported_question"


ClaimStatus = Literal["supported", "partial", "unsupported"]

# verified: every claim supported. partial: some unsupported claims were removed.
# unsupported: nothing was supported. unverified: the verifier itself failed.
VerificationStatus = Literal["verified", "partial", "unsupported", "unverified", "skipped"]


class ClaimVerification(BaseModel):
    claim: str
    supported: bool
    supporting_sources: list[int]
    confidence: float
    status: ClaimStatus = "supported"


class ConflictInfo(BaseModel):
    topic: str
    source_a: int
    claim_a: str
    source_b: int
    claim_b: str
    resolved: bool
    winning_source: int | None = None
    resolution_reason: str | None = None


class RAGResponse(BaseModel):
    answer: str
    citations: list[Citation]
    claim_verifications: list[ClaimVerification]
    conflicts: list[ConflictInfo] = []
    evidence_gate: EvidenceGateResult
    abstained: bool
    abstention_reason: AbstentionReason | None = None
    verification_status: VerificationStatus = "skipped"
    # Overall answer confidence: mean of supported-claim confidence when verification ran;
    # falls back to the top citation relevance score; 0.0 on abstention.
    confidence_score: float = 0.0
    retrieval_metadata: dict
    # Internal: persisted to rag_traces by the chat layer, never sent to clients.
    trace_stages: dict = Field(default_factory=dict, exclude=True)
    # Set by the chat layer when the conversation was handed to a human (V3 escalation).
    handoff: dict | None = None


def compute_confidence_score(
    claims: list[ClaimVerification],
    citations: list[Citation],
    abstained: bool,
) -> float:
    """Derive a [0, 1] confidence score for the answer."""
    if abstained:
        return 0.0
    supported = [c for c in claims if c.status == "supported"]
    if supported:
        return round(sum(c.confidence for c in supported) / len(supported), 4)
    if citations:
        return round(max(c.relevance_score for c in citations), 4)
    return 0.0
