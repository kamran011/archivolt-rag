from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.domains.auth.dependencies import require_org
from app.domains.auth.schemas import CurrentUser
from app.domains.retrieval.debug import DebugRequest, DebugResponse, retrieval_debugger
from app.domains.retrieval.schemas import RetrievalRequest, RetrievalResult
from app.domains.retrieval.service import retrieval_service

router = APIRouter()


@router.post(
    "/search",
    response_model=RetrievalResult,
    dependencies=[Depends(rate_limit("search", "RATE_LIMIT_SEARCH_PER_MIN"))],
)
async def search(
    request: RetrievalRequest,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    return await retrieval_service.retrieve(db, current_user.organization_id, request)


@router.post(
    "/debug",
    response_model=DebugResponse,
    dependencies=[Depends(rate_limit("search", "RATE_LIMIT_SEARCH_PER_MIN"))],
)
async def debug(
    request: DebugRequest,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    """Stage-by-stage retrieval trace (routing, engines, rerank, filters, gate,
    context). Same org scoping as /search; no answer is generated."""
    return await retrieval_debugger.run(db, current_user.organization_id, request)
