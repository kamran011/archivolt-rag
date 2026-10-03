"""
SQLAlchemy ORM model base classes.

These models are application-layer interfaces. Column definitions will be
aligned with docs/ARCHIVOLT_DATABASE_SPEC.md when the schema is finalized.
Supabase manages the actual database migrations via supabase/migrations/.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def portable_jsonb() -> JSON:
    """A JSON column type that compiles to real JSONB on Postgres (binary
    storage, indexable) and falls back to generic JSON elsewhere — e.g. the
    in-memory SQLite used by cross-tenant isolation tests. Production
    behavior on Postgres is unchanged; this only widens what else the
    models can run against."""
    return JSON().with_variant(JSONB(), "postgresql")


class TimestampMixin:
    # updated_at is refreshed by the database (onupdate=func.now()). Without this the
    # attribute is expired after an UPDATE flush and serializing the object in async code
    # fails (500 on every PATCH endpoint). eager_defaults fetches it via RETURNING.
    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
