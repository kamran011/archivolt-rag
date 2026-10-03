import uuid

from sqlalchemy import ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin, portable_jsonb


class DocumentRow(UUIDPrimaryKeyMixin, Base):
    """One record of a tabular document (CSV, or a JSON list of flat records), kept in
    queryable form for the structured_query tool. `data` maps normalized column name to a
    typed value (int, float or string)."""

    __tablename__ = "document_rows"
    __table_args__ = (Index("ix_document_rows_doc_row", "document_id", "row_index"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(portable_jsonb(), nullable=False)
