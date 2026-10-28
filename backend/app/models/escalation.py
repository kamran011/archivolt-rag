import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, portable_jsonb


class Escalation(UUIDPrimaryKeyMixin, Base):
    """A conversation handed to a human: why, where the team was notified, and its state."""

    __tablename__ = "escalations"
    __table_args__ = (Index("ix_escalations_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # the assistant reply
    trace_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # user_request | frustration | abstain
    reasons: Mapped[list] = mapped_column(portable_jsonb(), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # Per channel: "sent", "failed: ...", or "not_configured".
    delivery: Mapped[dict] = mapped_column(portable_jsonb(), nullable=False, default=dict)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
