from typing import TYPE_CHECKING

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, portable_jsonb

if TYPE_CHECKING:
    from app.models.knowledge_base import KnowledgeBase
    from app.models.organization_member import OrganizationMember


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(portable_jsonb(), default=dict, nullable=False)

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        "KnowledgeBase", back_populates="organization"
    )
