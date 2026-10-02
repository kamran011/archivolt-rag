"""Running an evaluation as a background job."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select, update

from app.domains.evals.service import RunConfig, utcnow
from app.domains.jobs import sessions
from app.domains.jobs.worker import JobHandler, PermanentJobError
from app.domains.retrieval.access import AccessScope
from app.evals.dataset import EvalCase
from app.evals.runner import run_eval
from app.models.eval_run import EvalDataset, EvalRun
from app.models.job import Job

logger = structlog.get_logger()


async def _run(job: Job) -> None:
    run_id = uuid.UUID(job.payload["run_id"])
    async with sessions.new_session() as db:
        run = (await db.execute(select(EvalRun).where(EvalRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise PermanentJobError("Run not found")
        ds = (
            await db.execute(select(EvalDataset).where(EvalDataset.id == run.dataset_id))
        ).scalar_one()
        org_id, created_by = run.organization_id, run.created_by
        kb_ids = [uuid.UUID(k) for k in run.knowledge_base_ids]
        cfg = RunConfig.model_validate(run.config)
        cases = [EvalCase.model_validate(c) for c in ds.cases]
        dataset_name = ds.name
        run.status = "running"
        await db.commit()

    scope = AccessScope(user_id=created_by, is_admin=cfg.access == "admin")
    report = await run_eval(
        sessions.new_session, org_id, kb_ids, cases,
        dataset_name=dataset_name, strategy=cfg.strategy, k=cfg.k, agentic=cfg.agentic,
        retrieval_only=cfg.retrieval_only, mode=cfg.mode, scope=scope,
    )
    async with sessions.new_session() as db:
        await db.execute(
            update(EvalRun).where(EvalRun.id == run_id).values(
                status="succeeded", summary=report.summary,
                results=[c.model_dump() for c in report.cases],
                total_cases=report.total_cases, failed_cases=report.failed_cases,
                finished_at=utcnow(),
            )
        )
        await db.commit()


async def _on_dead(job: Job, error: str) -> None:
    try:
        async with sessions.new_session() as db:
            await db.execute(
                update(EvalRun).where(EvalRun.id == uuid.UUID(job.payload["run_id"])).values(
                    status="failed", error=error[:2000], finished_at=utcnow()
                )
            )
            await db.commit()
    except Exception as e:  # bookkeeping must not mask the original error
        logger.error("eval_mark_failed_error", error=str(e))


eval_handler = JobHandler(run=_run, on_dead=_on_dead, timeout_s=840.0)  # must stay under JOB_LOCK_TIMEOUT_S or the job is reclaimed mid-run
