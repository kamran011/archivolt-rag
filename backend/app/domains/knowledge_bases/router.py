import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.domains.auth.dependencies import require_org, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.knowledge_bases.schemas import CagInfo, KBCreate, KBResponse, KBStats, KBUpdate
from app.domains.knowledge_bases.service import kb_service
from app.domains.retrieval.access import scope_for
from app.domains.retrieval.cag import load_cag_context
from app.models.organization_member import OrgRole

router = APIRouter()


@router.post("/", response_model=KBResponse, status_code=201)
async def create_kb(
    data: KBCreate,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin, OrgRole.member)
    ),
    db: AsyncSession = Depends(get_db),
):
    if data.cag_enabled and current_user.role not in (OrgRole.owner, OrgRole.admin):
        # CAG sends the whole KB to the LLM on every question: a cost decision for admins.
        raise ForbiddenError("Only owners and admins can enable CAG")
    kb = await kb_service.create(db, current_user.organization_id, data)
    return KBResponse.model_validate(kb)


@router.get("/", response_model=list[KBResponse])
async def list_kbs(
    include_archived: bool = False,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    kbs = await kb_service.list(db, current_user.organization_id, include_archived)
    return [KBResponse.model_validate(kb) for kb in kbs]


@router.get("/{kb_id}", response_model=KBResponse)
async def get_kb(
    kb_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get(db, current_user.organization_id, kb_id)
    return KBResponse.model_validate(kb)


@router.patch("/{kb_id}", response_model=KBResponse)
async def update_kb(
    kb_id: uuid.UUID,
    data: KBUpdate,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.update(db, current_user.organization_id, kb_id, data)
    return KBResponse.model_validate(kb)


@router.delete("/{kb_id}", status_code=204)
async def archive_kb(
    kb_id: uuid.UUID,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db),
):
    await kb_service.archive(db, current_user.organization_id, kb_id)


@router.get("/{kb_id}/stats", response_model=KBStats)
async def get_kb_stats(
    kb_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    return await kb_service.get_stats(db, current_user.organization_id, kb_id)


@router.get("/{kb_id}/cag", response_model=CagInfo)
async def cag_info(
    kb_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    """Is CAG usable for this knowledge base right now, for *this* caller? Size is measured
    over the content the caller can see, without loading any text."""
    kb = await kb_service.get(db, current_user.organization_id, kb_id)
    cag = await load_cag_context(
        db, current_user.organization_id, [kb_id], scope_for(current_user), load_text=False
    )
    return CagInfo(
        enabled=kb.cag_enabled,
        eligible=cag.eligible,
        reason=cag.reason,
        tokens=cag.total_tokens,
        limit=cag.limit,
    )
