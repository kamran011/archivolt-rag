"""Create escalations from chat turns and queue the team notification."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.escalation.detector import detect_reasons
from app.domains.escalation.settings import load_settings
from app.domains.jobs.queue import job_queue
from app.models.escalation import Escalation
from app.models.organization import Organization

logger = structlog.get_logger()

NOTIFY_KIND = "escalation_notify"


async def maybe_escalate(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID | None,
    message: str,
    earlier_user_messages: list[str],
    abstained: bool,
    assistant_message_id: uuid.UUID | None,
    trace_id: str | None,
) -> dict | None:
    """Hand the conversation to a human when a configured trigger fires.

    Returns what the client should show ({"status", "reasons", "message"}) or None.
    Never raises: a handoff problem must not fail the answer the user already has."""
    try:
        org = await db.get(Organization, org_id)
        rules = load_settings(org.settings if org else None)
        reasons = await detect_reasons(message, earlier_user_messages, abstained, rules)
        if not reasons:
            return None

        existing = (
            await db.execute(
                select(Escalation).where(
                    Escalation.conversation_id == conversation_id, Escalation.status == "open"
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # The team already has this conversation; don't notify them again.
            existing.reasons = sorted(set(existing.reasons) | set(reasons))
            await db.flush()
            return {"status": "already_open", "reasons": reasons,
                    "message": rules.customer_message}

        escalation = Escalation(
            organization_id=org_id,
            conversation_id=conversation_id,
            user_id=user_id,
            message_id=assistant_message_id,
            trace_id=uuid.UUID(trace_id) if trace_id else None,
            reasons=reasons,
            status="open",
            delivery={},
        )
        db.add(escalation)
        await db.flush()
        # Same transaction as the escalation row: both commit together, and the job worker
        # delivers (and retries) the Slack/email notification outside the request.
        await job_queue.enqueue(
            db, NOTIFY_KIND, {"escalation_id": str(escalation.id)},
            org_id=org_id, dedupe_key=f"esc:{escalation.id}",
        )
        logger.info("escalation_created", escalation_id=str(escalation.id), reasons=reasons)
        return {"status": "created", "reasons": reasons, "message": rules.customer_message}
    except Exception as e:  # noqa: BLE001
        logger.error("escalation_failed", error=str(e))
        return None
