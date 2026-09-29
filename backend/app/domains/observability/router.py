import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.domains.auth.dependencies import require_role
from app.domains.auth.schemas import CurrentUser
from app.models.organization_member import OrgRole
from app.models.rag_trace import RagTrace
from app.models.tool_audit import ToolAuditRecord

router = APIRouter()


class TraceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID | None
    query: str
    strategy: str | None
    abstained: bool
    abstention_reason: str | None
    verification_status: str | None
    total_ms: Decimal | None
    cost_usd: Decimal | None
    created_at: datetime


class TraceDetail(TraceSummary):
    spans: list | None
    stages: dict | None


@router.get("/traces", response_model=list[TraceSummary])
async def list_traces(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    abstained: bool | None = None,
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Recent RAG traces for the organization (admin/owner: traces contain user questions)."""
    stmt = select(RagTrace).where(RagTrace.organization_id == current_user.organization_id)
    if abstained is not None:
        stmt = stmt.where(RagTrace.abstained == abstained)
    stmt = stmt.order_by(RagTrace.created_at.desc()).limit(limit).offset(offset)
    return (await db.execute(stmt)).scalars().all()


class ToolCallView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    tool: str
    arguments: dict
    status: str
    duration_ms: Decimal
    result_chunks: int
    detail: str | None
    created_at: datetime


@router.get("/traces/{trace_id}/tool-calls", response_model=list[ToolCallView])
async def get_trace_tool_calls(
    trace_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Every tool call the agent attempted for this trace (including denied/failed ones)."""
    stmt = (
        select(ToolAuditRecord)
        .where(
            ToolAuditRecord.trace_id == trace_id,
            ToolAuditRecord.organization_id == current_user.organization_id,
        )
        .order_by(ToolAuditRecord.run_id, ToolAuditRecord.seq)
    )
    return (await db.execute(stmt)).scalars().all()


@router.get("/traces/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db),
):
    """Full stage-by-stage trace: what was retrieved, reranked, filtered, selected and
    cited, and why candidates were excluded. Org-scoped; other orgs' ids look like 404."""
    stmt = select(RagTrace).where(
        RagTrace.id == trace_id, RagTrace.organization_id == current_user.organization_id
    )
    trace = (await db.execute(stmt)).scalar_one_or_none()
    if trace is None:
        raise NotFoundError("Trace not found")
    return trace
