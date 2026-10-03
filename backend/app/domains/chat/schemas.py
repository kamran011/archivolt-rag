import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.models.message import MessageRole


class ChatRequest(BaseModel):
    message: str
    knowledge_base_ids: list[uuid.UUID]
    conversation_id: uuid.UUID | None = None
    model: str = Field(default_factory=lambda: settings.DEFAULT_LLM_MODEL)
    stream: bool = True
    agentic: bool = False
    web_search: bool = False  # allow external web results (still needs org opt-in)
    mode: Literal["rag", "cag", "hybrid"] = "rag"


class ConversationCreate(BaseModel):
    knowledge_base_id: uuid.UUID | None = None
    title: str | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID | None
    title: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    citations: list | None
    abstained: bool
    created_at: datetime
    # Trace/build metadata captured when the answer was generated (None for user
    # messages, and for assistant messages saved before this field existed).
    retrieval_metadata: dict | None = None
    token_usage: dict | None = None

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]
