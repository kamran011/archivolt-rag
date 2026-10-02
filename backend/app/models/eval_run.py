import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, portable_jsonb


class EvalDataset(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "eval_datasets"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    cases: Mapped[list] = mapped_column(portable_jsonb(), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvalRun(UUIDPrimaryKeyMixin, Base):
    """One configuration (strategy / mode / agentic ...) evaluated against one dataset."""

    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_org_created", "organization_id", "created_at"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    knowledge_base_ids: Mapped[list] = mapped_column(portable_jsonb(), nullable=False)
    config: Mapped[dict] = mapped_column(portable_jsonb(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    summary: Mapped[dict | None] = mapped_column(portable_jsonb(), nullable=True)
    results: Mapped[list | None] = mapped_column(portable_jsonb(), nullable=True)
    total_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
