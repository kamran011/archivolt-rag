import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, portable_jsonb

JOB_ACTIVE = ("queued", "running")


class Job(UUIDPrimaryKeyMixin, Base):
    """A unit of background work (e.g. ingest a document), claimed with FOR UPDATE SKIP LOCKED
    so any number of workers can run safely. status: queued -> running -> succeeded, or back
    to queued (retry with backoff), or failed (permanent error) / dead (retries exhausted)."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "run_after", postgresql_where=text("status = 'queued'")),
        # At most one active job per (kind, dedupe_key): a double-click cannot double-ingest.
        Index(
            "uq_jobs_active_dedupe", "kind", "dedupe_key", unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(portable_jsonb(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
