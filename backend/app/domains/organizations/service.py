import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.domains.organizations.schemas import OrgCreate, OrgMemberCreate, OrgMemberUpdate, OrgUpdate
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
        # Check not already a member
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
