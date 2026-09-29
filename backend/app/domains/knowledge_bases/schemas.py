import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.knowledge_base import ChunkStrategy, KBStatus


class KBCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = None
    chunk_strategy: ChunkStrategy = ChunkStrategy.structure_aware
    chunk_size: int = Field(default=512, ge=128, le=2048)
    chunk_overlap: int = Field(default=64, ge=0, le=256)
    embedding_model: str = "text-embedding-3-small"


class KBUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: KBStatus | None = None


class KBResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    embedding_model: str
    chunk_strategy: ChunkStrategy
    chunk_size: int
    chunk_overlap: int
    status: KBStatus
    document_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KBStats(BaseModel):
    document_count: int
    chunk_count: int
    total_tokens: int
    ready_documents: int
    failed_documents: int
    pending_documents: int
