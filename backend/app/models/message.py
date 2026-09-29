import uuid
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, portable_jsonb

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(portable_jsonb(), nullable=True)
    retrieval_metadata: Mapped[dict | None] = mapped_column(portable_jsonb(), nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(portable_jsonb(), nullable=True)
    abstained: Mapped[bool] = mapped_column(nullable=False, default=False)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
