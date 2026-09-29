import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_trace import RagTrace, UsageLedger
from app.models.tool_audit import ToolAuditRecord

logger = structlog.get_logger()


async def save_rag_trace(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    query: str,
    trace_id: str | None,
    stages: dict | None,
    abstained: bool,
    abstention_reason: str | None,
    verification_status: str | None,
    cost_usd: float | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    model: str | None,
) -> None:
    """Persist a trace row and its usage-ledger entry. Observability must never break
    the request it observes, so failures are logged and swallowed; the savepoint keeps
    a failed insert from poisoning the caller's transaction."""
    if not trace_id:
        return
    try:
        stages = dict(stages or {})
        meta = stages.pop("meta", {}) or {}
        async with db.begin_nested():
            db.add(
                RagTrace(
                    id=uuid.UUID(trace_id),
                    organization_id=org_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    query=query,
                    strategy=meta.get("strategy"),
                    abstained=abstained,
                    abstention_reason=abstention_reason,
                    verification_status=verification_status,
                    total_ms=meta.get("total_ms"),
                    cost_usd=cost_usd,
                    spans=meta.get("spans"),
                    stages=stages,
                )
            )
            await db.flush()  # trace row must exist before the ledger FK references it
            for call in meta.get("tool_audit") or []:
                db.add(
                    ToolAuditRecord(
                        organization_id=org_id,
                        user_id=user_id,
                        run_id=uuid.UUID(str(call["run_id"])),
                        trace_id=uuid.UUID(trace_id),
                        seq=call.get("seq") or 0,
                        tool=call["tool"],
                        arguments=call.get("arguments") or {},
                        status=call["status"],
                        duration_ms=call.get("duration_ms") or 0,
                        result_chunks=call.get("result_chunks") or 0,
                        detail=call.get("detail"),
                    )
                )
            if cost_usd or prompt_tokens or completion_tokens:
                db.add(
                    UsageLedger(
                        organization_id=org_id,
                        user_id=user_id,
                        trace_id=uuid.UUID(trace_id),
                        kind="llm",
                        model=model,
                        input_tokens=prompt_tokens or 0,
                        output_tokens=completion_tokens or 0,
                        cost_usd=cost_usd or 0,
                    )
                )
    except Exception as e:
        logger.error("save_rag_trace_failed", error=str(e), trace_id=trace_id)
