import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import get_current_user, require_role_in_path_org
from app.domains.auth.schemas import CurrentUser
from app.domains.organizations.schemas import (
    OrgCreate,
    OrgMemberCreate,
    OrgMemberResponse,
    OrgMemberUpdate,
    OrgResponse,
    OrgUpdate,
)
from app.domains.organizations.service import org_service
from app.models.organization_member import OrgRole

router = APIRouter()


@router.post("/", response_model=OrgResponse, status_code=201)
async def create_org(
    data: OrgCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await org_service.create(db, current_user.id, data)
    count = await org_service.member_count(db, org.id)
    return OrgResponse(**org.__dict__, member_count=count, role=OrgRole.owner)


@router.get("/", response_model=list[OrgResponse])
async def list_orgs(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    orgs = await org_service.list_for_user(db, current_user.id)
    return [OrgResponse(**o.__dict__) for o in orgs]


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = await org_service.get(db, org_id, current_user.id)
    count = await org_service.member_count(db, org.id)
    return OrgResponse(**org.__dict__, member_count=count, role=current_user.role)


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: uuid.UUID,
    data: OrgUpdate,
    current_user: CurrentUser = Depends(
        require_role_in_path_org(OrgRole.admin, OrgRole.owner)
    ),
    db: AsyncSession = Depends(get_db),
):
    org = await org_service.update(db, org_id, data)
    count = await org_service.member_count(db, org.id)
    return OrgResponse(**org.__dict__, member_count=count, role=current_user.role)


@router.get("/{org_id}/members", response_model=list[OrgMemberResponse])
async def list_members(
    org_id: uuid.UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify membership first
    await org_service.get(db, org_id, current_user.id)
    members = await org_service.list_members(db, org_id)
    return [OrgMemberResponse.model_validate(m) for m in members]


@router.post("/{org_id}/members", response_model=OrgMemberResponse, status_code=201)
async def add_member(
    org_id: uuid.UUID,
    data: OrgMemberCreate,
    current_user: CurrentUser = Depends(
        require_role_in_path_org(OrgRole.admin, OrgRole.owner)
    ),
    db: AsyncSession = Depends(get_db),
):
    member = await org_service.add_member(db, org_id, data)
    return OrgMemberResponse.model_validate(member)


@router.patch("/{org_id}/members/{member_id}", response_model=OrgMemberResponse)
async def update_member_role(
    org_id: uuid.UUID,
    member_id: uuid.UUID,
    data: OrgMemberUpdate,
    current_user: CurrentUser = Depends(require_role_in_path_org(OrgRole.owner)),
    db: AsyncSession = Depends(get_db),
):
    member = await org_service.update_member_role(db, org_id, member_id, data)
    return OrgMemberResponse.model_validate(member)


@router.delete("/{org_id}/members/{member_id}", status_code=204)
async def remove_member(
    org_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: CurrentUser = Depends(
        require_role_in_path_org(OrgRole.admin, OrgRole.owner)
    ),
    db: AsyncSession = Depends(get_db),
):
    await org_service.remove_member(db, org_id, member_id, current_user.id)
