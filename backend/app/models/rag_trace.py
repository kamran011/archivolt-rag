import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, portable_jsonb


class RagTrace(Base):
    """One row per answered (or abstained) RAG request: which evidence moved through
    each stage and why candidates were excluded. Holds chunk/document ids and scores, not
    chunk text."""

    __tablename__ = "rag_traces"
    __table_args__ = (Index("ix_rag_traces_org_created", "organization_id", "created_at"),)

    # Same id the request's in-memory RetrievalTrace used, so logs and rows correlate.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    abstention_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_ms: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    spans: Mapped[list | None] = mapped_column(portable_jsonb(), nullable=True)
    stages: Mapped[dict | None] = mapped_column(portable_jsonb(), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UsageLedger(Base):
    """Append-only record of billable/measurable AI usage per organization."""

    __tablename__ = "usage_ledger"
    __table_args__ = (Index("ix_usage_ledger_org_created", "organization_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rag_traces.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # llm|embedding|rerank|vision|tool
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
