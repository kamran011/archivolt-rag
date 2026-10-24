import uuid
from datetime import datetime, timezone

import structlog
from supabase import create_client
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.domains.organizations.schemas import OrgCreate, OrgInvitationCreate, OrgMemberCreate, OrgMemberUpdate, OrgUpdate
from app.models.org_invitation import OrgInvitation
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrgRole

logger = structlog.get_logger()


class OrganizationService:
    async def create(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        data: OrgCreate,
    ) -> Organization:
        # Check slug uniqueness
        existing = await db.execute(
            select(Organization).where(Organization.slug == data.slug)
        )
        if existing.scalar_one_or_none():
            raise ValidationError(f"Slug '{data.slug}' is already taken")

        org = Organization(
            name=data.name,
            slug=data.slug,
            description=data.description,
        )
        db.add(org)
        await db.flush()  # get org.id before creating member

        # Creator becomes owner
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user_id,
            role=OrgRole.owner,
        )
        db.add(member)
        await db.flush()

        logger.info("org_created", org_id=str(org.id), user_id=str(user_id))
        return org

    async def get(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Organization:
        org = await db.get(Organization, org_id)
        if not org:
            raise NotFoundError(f"Organization {org_id} not found")

        # Verify membership
        member = await self._get_member(db, org_id, user_id)
        if not member:
            raise ForbiddenError("Not a member of this organization")

        return org

    async def list_for_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[tuple[Organization, OrgRole, int]]:
        """The caller's organizations with their role in each and the member count."""
        my_orgs = select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == user_id
        )
        counts = (
            select(
                OrganizationMember.organization_id.label("org_id"),
                func.count().label("n"),
            )
            .where(OrganizationMember.organization_id.in_(my_orgs))
            .group_by(OrganizationMember.organization_id)
            .subquery()
        )
        stmt = (
            select(Organization, OrganizationMember.role, counts.c.n)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .join(counts, counts.c.org_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at.desc())
        )
        result = await db.execute(stmt)
        return [(org, role, n) for org, role, n in result.all()]

    async def member_role(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrgRole | None:
        stmt = select(OrganizationMember.role).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        data: OrgUpdate,
    ) -> Organization:
        org = await db.get(Organization, org_id)
        if not org:
            raise NotFoundError(f"Organization {org_id} not found")

        if data.name is not None:
            org.name = data.name
        if data.description is not None:
            org.description = data.description
        if data.settings is not None:
            org.settings = {**org.settings, **data.settings}

        await db.flush()
        return org

    async def add_member(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        data: OrgMemberCreate,
    ) -> OrganizationMember:
        existing = await self._get_member(db, org_id, data.user_id)
        if existing:
            raise ValidationError("User is already a member of this organization")

        member = OrganizationMember(
            organization_id=org_id,
            user_id=data.user_id,
            role=data.role,
        )
        db.add(member)
        await db.flush()
        return member

    async def create_invitation(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        invited_by: uuid.UUID,
        data: OrgInvitationCreate,
    ) -> OrgInvitation:
        # Verify not already a member (look up by email via Supabase admin)
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        users = supabase.auth.admin.list_users()
        existing_user_id: uuid.UUID | None = None
        for u in users:
            if u.email and u.email.lower() == data.email.lower():
                existing_user_id = uuid.UUID(u.id)
                break

        if existing_user_id:
            member = await self._get_member(db, org_id, existing_user_id)
            if member:
                raise ValidationError("This user is already a member of the organization.")

        # Check no pending invite already exists for this email+org
        stmt = select(OrgInvitation).where(
            OrgInvitation.org_id == org_id,
            OrgInvitation.accepted_at.is_(None),
        )
        result = await db.execute(stmt)
        for inv in result.scalars().all():
            if inv.email.lower() == data.email.lower():
                raise ValidationError("An invitation has already been sent to this email address.")

        invite = OrgInvitation(
            org_id=org_id,
            email=data.email,
            role=data.role,
            invited_by=invited_by,
        )
        db.add(invite)
        await db.flush()

        # Send the invite email via Supabase Admin API
        redirect_to = (
            f"{settings.FRONTEND_URL}/invite/accept"
            f"?invite={invite.id}&org={org_id}"
        )
        supabase.auth.admin.invite_user_by_email(
            data.email,
            options={"redirect_to": redirect_to},
        )

        logger.info("invitation_sent", invite_id=str(invite.id), org_id=str(org_id), email=data.email)
        return invite

    async def resend_invitation(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        invite_id: uuid.UUID,
    ) -> OrgInvitation:
        invite = await db.get(OrgInvitation, invite_id)
        if not invite or invite.org_id != org_id:
            raise NotFoundError("Invitation not found.")
        if invite.accepted_at is not None:
            raise ValidationError("This invitation has already been accepted.")

        redirect_to = (
            f"{settings.FRONTEND_URL}/invite/accept"
            f"?invite={invite.id}&org={org_id}"
        )
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

        # Generate a fresh invite link (does not send email itself)
        link_response = supabase.auth.admin.generate_link({
            "type": "invite",
            "email": invite.email,
            "options": {"redirect_to": redirect_to},
        })
        action_link = link_response.properties.action_link

        # Send the email directly via Resend HTTP API
        if not settings.RESEND_API_KEY:
            raise ValidationError("Email service is not configured (RESEND_API_KEY missing).")

        import httpx
        html = (
            f"<p>You've been invited to join an organization on Ragix.</p>"
            f"<p><a href='{action_link}' style='background:#6a35ff;color:#fff;padding:10px 20px;"
            f"border-radius:8px;text-decoration:none;display:inline-block;'>Accept invitation</a></p>"
            f"<p>This link expires in 24 hours. If you didn't expect this email, you can ignore it.</p>"
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.EMAIL_FROM,
                    "to": invite.email,
                    "subject": "You've been invited to join Ragix",
                    "html": html,
                },
                timeout=10,
            )
            resp.raise_for_status()

        logger.info("invitation_resent", invite_id=str(invite.id), org_id=str(org_id), email=invite.email)
        return invite

    async def revoke_invitation(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        invite_id: uuid.UUID,
    ) -> None:
        invite = await db.get(OrgInvitation, invite_id)
        if not invite or invite.org_id != org_id:
            raise NotFoundError("Invitation not found.")
        if invite.accepted_at is not None:
            raise ValidationError("This invitation has already been accepted.")
        await db.delete(invite)
        logger.info("invitation_revoked", invite_id=str(invite.id), org_id=str(org_id))

    async def accept_invitation(
        self,
        db: AsyncSession,
        invite_id: uuid.UUID,
        user_id: uuid.UUID,
        user_email: str,
    ) -> OrganizationMember:
        invite = await db.get(OrgInvitation, invite_id)
        if not invite:
            raise NotFoundError("Invitation not found or already used.")
        if invite.accepted_at is not None:
            raise ValidationError("This invitation has already been accepted.")
        if invite.email.lower() != user_email.lower():
            raise ForbiddenError("This invitation was sent to a different email address.")

        # Check not already a member
        existing = await self._get_member(db, invite.org_id, user_id)
        if existing:
            raise ValidationError("You are already a member of this organization.")

        member = OrganizationMember(
            organization_id=invite.org_id,
            user_id=user_id,
            role=invite.role,
        )
        db.add(member)

        invite.accepted_at = datetime.now(timezone.utc)
        await db.flush()

        logger.info("invitation_accepted", invite_id=str(invite_id), user_id=str(user_id))
        return member

    async def list_invitations(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> list[OrgInvitation]:
        stmt = select(OrgInvitation).where(
            OrgInvitation.org_id == org_id,
            OrgInvitation.accepted_at.is_(None),
        ).order_by(OrgInvitation.created_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def remove_member(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        member_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
    ) -> None:
        member = await db.get(OrganizationMember, member_id)
        if not member or member.organization_id != org_id:
            raise NotFoundError("Member not found")

        # Can't remove the last owner
        if member.role == OrgRole.owner:
            owner_count_stmt = select(func.count()).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.role == OrgRole.owner,
            )
            result = await db.execute(owner_count_stmt)
            if result.scalar() <= 1:
                raise ValidationError("Cannot remove the last owner")

        await db.delete(member)
        await db.flush()

    async def update_member_role(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        member_id: uuid.UUID,
        data: OrgMemberUpdate,
    ) -> OrganizationMember:
        member = await db.get(OrganizationMember, member_id)
        if not member or member.organization_id != org_id:
            raise NotFoundError("Member not found")

        member.role = data.role
        await db.flush()
        return member

    async def list_members(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> list[OrganizationMember]:
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def member_count(self, db: AsyncSession, org_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(OrganizationMember.organization_id == org_id)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def _get_member(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> OrganizationMember | None:
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


org_service = OrganizationService()
