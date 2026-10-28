"""Job handler: deliver an escalation to the team (Slack incoming webhook and/or email).

Everything in the notification is escaped/plain text: it contains customer messages."""

from __future__ import annotations

import html
import uuid

import httpx
import structlog
from sqlalchemy import select

from app.config import settings
from app.domains.escalation.settings import load_settings
from app.domains.jobs import sessions
from app.domains.jobs.worker import JobHandler, PermanentJobError
from app.models.conversation import Conversation
from app.models.escalation import Escalation
from app.models.job import Job
from app.models.message import Message
from app.models.organization import Organization

logger = structlog.get_logger()

MAX_TRANSCRIPT_MESSAGES = 20
MAX_MESSAGE_CHARS = 1200
REASON_LABELS = {
    "user_request": "Customer asked for a human",
    "frustration": "Customer seems frustrated",
    "abstain": "The assistant could not answer from the knowledge base",
}


def escalation_link(escalation_id: uuid.UUID) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/dashboard/escalations?id={escalation_id}"


def _transcript(messages: list[Message]) -> list[dict]:
    out = []
    for m in messages[-MAX_TRANSCRIPT_MESSAGES:]:
        entry = {"role": m.role.value, "content": m.content[:MAX_MESSAGE_CHARS]}
        if m.role.value == "assistant":
            md = m.retrieval_metadata or {}
            entry["abstained"] = bool(m.abstained)
            entry["abstention_reason"] = md.get("abstention_reason")
            entry["sources"] = sorted({c.get("document_title", "") for c in (m.citations or [])})
        out.append(entry)
    return out


def _text_body(org_name: str, reasons: list[str], transcript: list[dict], link: str) -> str:
    lines = [f"Ragix handoff for {org_name}", ""]
    lines += [f"- {REASON_LABELS.get(r, r)}" for r in reasons]
    lines += ["", "Conversation:"]
    for t in transcript:
        who = "Customer" if t["role"] == "user" else "Assistant"
        lines.append(f"{who}: {t['content']}")
        if t.get("abstained"):
            lines.append(f"  (abstained: {t.get('abstention_reason') or 'insufficient evidence'})")
        if t.get("sources"):
            lines.append(f"  (sources: {', '.join(s for s in t['sources'] if s)})")
    lines += ["", f"Open in Ragix: {link}"]
    return "\n".join(lines)


def _html_body(org_name: str, reasons: list[str], transcript: list[dict], link: str) -> str:
    e = html.escape
    rows = []
    for t in transcript:
        who = "Customer" if t["role"] == "user" else "Assistant"
        extra = ""
        if t.get("abstained"):
            extra += f"<br><i>abstained: {e(t.get('abstention_reason') or 'insufficient evidence')}</i>"
        if t.get("sources"):
            extra += f"<br><i>sources: {e(', '.join(s for s in t['sources'] if s))}</i>"
        rows.append(f"<p><b>{who}:</b> {e(t['content'])}{extra}</p>")
    reason_items = "".join(f"<li>{e(REASON_LABELS.get(r, r))}</li>" for r in reasons)
    return (
        f"<h3>Ragix handoff for {e(org_name)}</h3><ul>{reason_items}</ul>"
        f"{''.join(rows)}"
        f"<p><a href='{e(link)}'>Open this conversation in Ragix</a></p>"
    )


async def _send_slack(url: str, text: str) -> None:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        r = await client.post(url, json={"text": text})
        r.raise_for_status()


async def _send_email(to: list[str], subject: str, html_body: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={"from": settings.EMAIL_FROM, "to": to, "subject": subject, "html": html_body},
        )
        r.raise_for_status()


async def deliver(escalation: Escalation, org: Organization, messages: list[Message]) -> dict:
    """Send to every configured channel. Returns per-channel results."""
    rules = load_settings(org.settings)
    transcript = _transcript(messages)
    link = escalation_link(escalation.id)
    reasons = list(escalation.reasons or [])
    results: dict[str, str] = {}

    if rules.slack_webhook_url:
        try:
            await _send_slack(rules.slack_webhook_url,
                              _text_body(org.name, reasons, transcript, link))
            results["slack"] = "sent"
        except Exception as e:  # noqa: BLE001
            results["slack"] = f"failed: {type(e).__name__}"
    else:
        results["slack"] = "not_configured"

    if rules.emails and settings.RESEND_API_KEY:
        try:
            await _send_email(
                [str(a) for a in rules.emails],
                f"[Ragix] Conversation needs a human ({', '.join(reasons)})",
                _html_body(org.name, reasons, transcript, link),
            )
            results["email"] = "sent"
        except Exception as e:  # noqa: BLE001
            results["email"] = f"failed: {type(e).__name__}"
    else:
        results["email"] = "not_configured"
    return results


async def _run(job: Job) -> None:
    escalation_id = uuid.UUID(job.payload["escalation_id"])
    async with sessions.new_session() as db:
        escalation = await db.get(Escalation, escalation_id)
        if escalation is None:
            raise PermanentJobError("escalation not found")
        org = await db.get(Organization, escalation.organization_id)
        conversation = await db.get(Conversation, escalation.conversation_id)
        if org is None or conversation is None:
            raise PermanentJobError("organization or conversation not found")
        messages = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at)
            )
        ).scalars().all()

        results = await deliver(escalation, org, list(messages))
        escalation.delivery = results
        await db.commit()
        logger.info("escalation_delivered", escalation_id=str(escalation_id), delivery=results)

        attempted = [v for v in results.values() if v != "not_configured"]
        if attempted and all(v.startswith("failed") for v in attempted):
            raise RuntimeError(f"all notification channels failed: {results}")  # retried


escalation_notify_handler = JobHandler(run=_run)
