import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, portable_jsonb

if TYPE_CHECKING:
    from app.models.chunk import Chunk
    from app.models.knowledge_base import KnowledgeBase


class FileType(str, Enum):
    pdf = "pdf"
    docx = "docx"
    md = "md"
    txt = "txt"
    html = "html"
    csv = "csv"
    json = "json"
    image = "image"


class DocumentStatus(str, Enum):
    pending = "pending"
    parsing = "parsing"
    chunking = "chunking"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


class AuthorityTier(str, Enum):
    """Source priority used to break ties when evidence conflicts."""

    authoritative = "authoritative"  # official policy docs, contracts, specs
    standard = "standard"  # general internal documentation
    draft = "draft"  # unreviewed, working, or user-submitted content


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[FileType] = mapped_column(nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    # sha256 of the raw uploaded bytes; powers the duplicate-upload guard (see
    # DocumentService._find_duplicate_file). Nullable: documents stored before this field
    # existed have none.
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=False)
    status: Mapped[DocumentStatus] = mapped_column(
        nullable=False, default=DocumentStatus.pending
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parsing_metadata: Mapped[dict | None] = mapped_column(portable_jsonb(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # Versioning, freshness, and authority (Phase 2 — Production Safety)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True)
    supersedes_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    authority_tier: Mapped[AuthorityTier] = mapped_column(
        nullable=False, default=AuthorityTier.standard
    )

    # Free-form labels for filtering (list of strings).
    tags: Mapped[list] = mapped_column(portable_jsonb(), nullable=False, default=list)
    # Document-level access control. False (default): every org member can see it.
    # True: only owners/admins, the uploader, and users granted in document_access.
    restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentAccess(UUIDPrimaryKeyMixin, Base):
    """Explicit grant letting one user see a restricted document."""

    __tablename__ = "document_access"
    __table_args__ = (UniqueConstraint("document_id", "user_id", name="uq_document_access"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
