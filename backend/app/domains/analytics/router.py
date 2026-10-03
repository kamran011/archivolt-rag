from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.analytics.service import UsageSummary, analytics_service
from app.domains.auth.dependencies import require_role
from app.domains.auth.schemas import CurrentUser
from app.models.organization_member import OrgRole

router = APIRouter()


@router.get("/usage", response_model=UsageSummary)
async def usage(
    days: int = Query(default=30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Org-wide usage, abstention and cost figures. Admin/owner only because it
    exposes spend across all members."""
    return await analytics_service.usage(db, current_user.organization_id, days)
