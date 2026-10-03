import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, portable_jsonb


class ToolAuditRecord(UUIDPrimaryKeyMixin, Base):
    """One row per tool call attempt made by the agent (including denied/invalid/failed)."""

    __tablename__ = "tool_audit"
    __table_args__ = (Index("ix_tool_audit_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    run_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool: Mapped[str] = mapped_column(String(60), nullable=False)
    arguments: Mapped[dict] = mapped_column(portable_jsonb(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    result_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
