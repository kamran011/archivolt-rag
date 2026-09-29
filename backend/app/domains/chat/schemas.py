import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.message import MessageRole


class ChatRequest(BaseModel):
    message: str
    knowledge_base_ids: list[uuid.UUID]
    conversation_id: uuid.UUID | None = None
    model: str = "gpt-4o"
    stream: bool = True
    agentic: bool = False
    web_search: bool = False  # allow external web results (still needs org opt-in)


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

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]
