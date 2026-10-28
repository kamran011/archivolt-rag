"""Escalation inbox and handoff settings. Owners/admins only: escalations expose users'
conversations, like traces."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.domains.auth.dependencies import require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.escalation.schemas import EscalationDetail, EscalationSummary, TranscriptMessage
from app.domains.escalation.settings import EscalationSettings, load_settings
from app.models.conversation import Conversation
from app.models.escalation import Escalation
from app.models.message import Message
from app.models.organization import Organization
from app.models.organization_member import OrgRole

router = APIRouter()
admin = require_role(OrgRole.owner, OrgRole.admin)


@router.get("/settings", response_model=EscalationSettings)
async def get_settings(
    current_user: CurrentUser = Depends(admin), db: AsyncSession = Depends(get_db, scope="function")
) -> EscalationSettings:
    org = await db.get(Organization, current_user.organization_id)
    return load_settings(org.settings if org else None)


@router.put("/settings", response_model=EscalationSettings)
async def put_settings(
    body: EscalationSettings,
    current_user: CurrentUser = Depends(admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> EscalationSettings:
    org = await db.get(Organization, current_user.organization_id)
    if org is None:
        raise NotFoundError("Organization not found")
    org.settings = {**(org.settings or {}), "escalation": body.model_dump(mode="json")}
    await db.flush()
    return body


async def _get(db: AsyncSession, org_id: uuid.UUID, escalation_id: uuid.UUID) -> Escalation:
    esc = await db.get(Escalation, escalation_id)
    if esc is None or esc.organization_id != org_id:
        raise NotFoundError("Escalation not found")
    return esc


@router.get("/", response_model=list[EscalationSummary])
async def list_escalations(
    status: str | None = Query(default=None, pattern="^(open|resolved)$"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[EscalationSummary]:
    stmt = (
        select(Escalation, Conversation.title)
        .join(Conversation, Conversation.id == Escalation.conversation_id)
        .where(Escalation.organization_id == current_user.organization_id)
        .order_by(Escalation.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Escalation.status == status)
    rows = (await db.execute(stmt)).all()
    return [
        EscalationSummary.model_validate(
            {**_fields(esc), "conversation_title": title}
        )
        for esc, title in rows
    ]


def _fields(esc: Escalation) -> dict:
    return {
        "id": esc.id, "conversation_id": esc.conversation_id, "user_id": esc.user_id,
        "reasons": esc.reasons or [], "status": esc.status, "delivery": esc.delivery or {},
        "created_at": esc.created_at, "resolved_at": esc.resolved_at, "trace_id": esc.trace_id,
    }


@router.get("/{escalation_id}", response_model=EscalationDetail)
async def get_escalation(
    escalation_id: uuid.UUID,
    current_user: CurrentUser = Depends(admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> EscalationDetail:
    esc = await _get(db, current_user.organization_id, escalation_id)
    conversation = await db.get(Conversation, esc.conversation_id)
    messages = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == esc.conversation_id)
            .order_by(Message.created_at)
        )
    ).scalars().all()
    return EscalationDetail.model_validate(
        {
            **_fields(esc),
            "conversation_title": conversation.title if conversation else None,
            "transcript": [
                TranscriptMessage(
                    role=m.role.value, content=m.content, created_at=m.created_at,
                    abstained=bool(m.abstained), citations=m.citations or [],
                )
                for m in messages
            ],
        }
    )


@router.post("/{escalation_id}/resolve", response_model=EscalationSummary)
async def resolve_escalation(
    escalation_id: uuid.UUID,
    current_user: CurrentUser = Depends(admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> EscalationSummary:
    esc = await _get(db, current_user.organization_id, escalation_id)
    if esc.status != "resolved":
        esc.status = "resolved"
        esc.resolved_at = datetime.now(UTC)
        esc.resolved_by = current_user.id
        await db.flush()
    return EscalationSummary.model_validate(_fields(esc))
