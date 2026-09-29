import uuid

from pydantic import BaseModel

from app.domains.retrieval.evidence_gate import EvidenceGateResult


class RAGRequest(BaseModel):
    query: str
    knowledge_base_ids: list[uuid.UUID]
    conversation_history: list[dict] | None = None
    model: str = "gpt-4o"
    temperature: float = 0.1
    agentic: bool = False


class Citation(BaseModel):
    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    page_number: int | None = None
    relevance_score: float


class ClaimVerification(BaseModel):
    claim: str
    supported: bool
    supporting_sources: list[int]
    confidence: float


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
    retrieval_metadata: dict
