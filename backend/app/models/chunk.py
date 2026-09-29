import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin, portable_jsonb

if TYPE_CHECKING:
    from app.models.document import Document


class Chunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_kb_org", "knowledge_base_id", "organization_id"),
        Index("ix_chunks_doc", "document_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", portable_jsonb(), default=dict, nullable=False
    )

    # pgvector column — populated after embedding
    embedding = mapped_column(Vector(1536), nullable=True)

    # Full-text search vector — populated during insert
    fts_vector = mapped_column(TSVECTOR, nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
