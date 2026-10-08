from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.domains.auth.dependencies import require_org, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.retrieval.access import scope_for
from app.domains.retrieval.debug import DebugRequest, DebugResponse, retrieval_debugger
from app.domains.retrieval.schemas import RetrievalRequest, RetrievalResult
from app.domains.retrieval.service import retrieval_service
from app.models.organization_member import OrgRole

router = APIRouter()
admin_only = require_role(OrgRole.owner, OrgRole.admin)


@router.post(
    "/search",
    response_model=RetrievalResult,
    dependencies=[Depends(rate_limit("search", "RATE_LIMIT_SEARCH_PER_MIN"))],
)
async def search(
    request: RetrievalRequest,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await retrieval_service.retrieve(
        db, current_user.organization_id, request, scope=scope_for(current_user)
    )


@router.post(
    "/debug",
    response_model=DebugResponse,
    dependencies=[Depends(rate_limit("search", "RATE_LIMIT_SEARCH_PER_MIN"))],
)
async def debug(
    request: DebugRequest,
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Stage-by-stage retrieval trace (routing, engines, rerank, filters, gate,
    context). Admin/owner only — exposes why each chunk was kept or dropped,
    which is an internal debugging view, not something a regular member needs."""
    return await retrieval_debugger.run(
        db, current_user.organization_id, request, scope_for(current_user)
    )
