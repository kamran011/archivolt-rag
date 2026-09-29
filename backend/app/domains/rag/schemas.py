import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.domains.retrieval.evidence_gate import EvidenceGateResult


class RAGRequest(BaseModel):
    query: str
    knowledge_base_ids: list[uuid.UUID]
    conversation_history: list[dict] | None = None
    model: str = "gpt-4o"
    temperature: float = 0.1
    agentic: bool = False
    web_search: bool = False  # the user asked to allow external web results


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
    retrieval_metadata: dict
    # Internal: persisted to rag_traces by the chat layer, never sent to clients.
    trace_stages: dict = Field(default_factory=dict, exclude=True)
