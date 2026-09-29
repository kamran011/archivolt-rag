import uuid
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.organization import Organization


class ChunkStrategy(str, Enum):
    fixed = "fixed"
    structure_aware = "structure_aware"
    semantic = "semantic"
    agentic = "agentic"


class KBStatus(str, Enum):
    active = "active"
    archived = "archived"


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(
        String(100), nullable=False, default="text-embedding-3-small"
    )
    chunk_strategy: Mapped[ChunkStrategy] = mapped_column(
        nullable=False, default=ChunkStrategy.structure_aware
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
    status: Mapped[KBStatus] = mapped_column(nullable=False, default=KBStatus.active)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Allows CAG (full-context answering) for this KB. Only meaningful for small, stable KBs;
    # requests still fall back to RAG when the KB does not fit the CAG token budget.
    cag_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="knowledge_bases"
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="knowledge_base"
    )
