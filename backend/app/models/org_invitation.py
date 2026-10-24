import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.organization_member import OrgRole

if TYPE_CHECKING:
    from app.models.organization import Organization


class OrgInvitation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "org_invitations"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[OrgRole] = mapped_column(nullable=False, default=OrgRole.member)
    invited_by: Mapped[uuid.UUID] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    organization: Mapped["Organization"] = relationship("Organization")
