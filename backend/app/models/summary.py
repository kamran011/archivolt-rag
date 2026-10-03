import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class DocumentSummary(UUIDPrimaryKeyMixin, Base):
    """Navigation summary of a document (level='document', node_id NULL) or of one section
    of its heading tree (level='section', node_id = TreeNode.node_id).

    Summaries are model-written from untrusted text and exist only to *find* documents and
    sections. They are never returned as evidence; retrieval always ends in raw chunks."""

    __tablename__ = "document_summaries"
    __table_args__ = (
        UniqueConstraint("document_id", "level", "node_id", name="uq_document_summary"),
        Index("ix_document_summaries_kb", "knowledge_base_id", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=True)
