import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.document import AuthorityTier, DocumentStatus, FileType


class DocumentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    file_name: str
    file_type: FileType
    file_size: int
    status: DocumentStatus
    page_count: int | None
    chunk_count: int
    error_message: str | None
    version: int
    is_current: bool
    supersedes_document_id: uuid.UUID | None
    superseded_at: datetime | None
    effective_date: datetime | None
    authority_tier: AuthorityTier
    tags: list[str] = []
    restricted: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentDetailResponse(DocumentResponse):
    parsing_metadata: dict | None
    storage_path: str


class DocumentUpdate(BaseModel):
    authority_tier: AuthorityTier | None = None
    effective_date: datetime | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    restricted: bool | None = None


class SignedUrlResponse(BaseModel):
    url: str
    expires_in: int


class ChunkView(BaseModel):
    id: uuid.UUID
    chunk_index: int
    token_count: int
    content: str
    metadata: dict
    has_embedding: bool


class ChunkPage(BaseModel):
    total: int
    items: list[ChunkView]


class DocumentTree(BaseModel):
    document_id: uuid.UUID
    # Heading outline built at ingestion (nodes map to chunk indices); empty if the
    # document has no headings or predates tree building.
    nodes: list[dict]


class SummaryView(BaseModel):
    level: str
    node_id: str | None
    title: str
    summary: str


class DocumentSummaries(BaseModel):
    document_id: uuid.UUID
    items: list[SummaryView]
