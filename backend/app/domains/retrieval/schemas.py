import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RetrievalStrategy = Literal["semantic", "keyword", "hybrid", "tree"]


class RetrievalFilters(BaseModel):
    document_ids: list[uuid.UUID] | None = None
    file_types: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    include_superseded: bool = False
    """By default, only the current version of each document is searched.
    Set True for historical queries that should also see superseded versions."""
    tags: list[str] | None = None
    """Match documents carrying ANY of these tags."""
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    as_of: datetime | None = None
    """Only documents whose effective date is on/before this instant (or undated). Combine
    with include_superseded=True to answer 'what did the policy say on <date>'."""
    min_authority: str | None = None
    """One of AuthorityTier values ('draft', 'standard', 'authoritative').
    When set, excludes evidence below this authority tier."""


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1)
    knowledge_base_ids: list[uuid.UUID]
    strategy: RetrievalStrategy = "hybrid"
    top_k: int = Field(default=20, ge=1, le=100)
    filters: RetrievalFilters | None = None


class RetrievedChunk(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    score: float
    metadata: dict
    retrieval_method: str
    is_current: bool = True
    authority_tier: str = "standard"
    document_version: int = 1
    effective_date: datetime | None = None


class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk]
    query: str
    strategy: RetrievalStrategy
    total_candidates: int
    retrieval_time_ms: float
