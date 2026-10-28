import uuid
from datetime import datetime

from pydantic import BaseModel


class EscalationSummary(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    conversation_title: str | None = None
    user_id: uuid.UUID | None
    reasons: list[str]
    status: str
    delivery: dict
    created_at: datetime
    resolved_at: datetime | None = None


class TranscriptMessage(BaseModel):
    role: str
    content: str
    created_at: datetime
    abstained: bool = False
    citations: list[dict] = []


class EscalationDetail(EscalationSummary):
    trace_id: uuid.UUID | None = None
    transcript: list[TranscriptMessage]
