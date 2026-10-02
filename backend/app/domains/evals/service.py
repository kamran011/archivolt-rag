"""Evaluation datasets and runs, org-scoped. Runs execute as background jobs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.domains.jobs.queue import job_queue
from app.evals.dataset import parse_dataset
from app.evals.report import MetricDelta, compare
from app.models.eval_run import EvalDataset, EvalRun
from app.models.knowledge_base import KnowledgeBase

EVAL_KIND = "eval_run"
MAX_CASES = 500
MAX_DATASET_CHARS = 1_000_000
MAX_CONFIGS = 8


class RunConfig(BaseModel):
    strategy: Literal["semantic", "keyword", "hybrid", "tree", "summary"] = "hybrid"
    mode: Literal["rag", "cag", "hybrid"] = "rag"
    agentic: bool = False
    k: int = Field(default=5, ge=1, le=20)
    retrieval_only: bool = False
    # "restricted" = least-privileged caller (shows whether restricted content leaks);
    # "admin" = evaluate as an admin.
    access: Literal["restricted", "admin"] = "restricted"


class EvalService:
    async def create_dataset(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, name: str, jsonl: str
    ) -> EvalDataset:
        if len(jsonl) > MAX_DATASET_CHARS:
            raise ValidationError("Dataset is too large")
        try:
            cases = parse_dataset(jsonl, name)
        except ValueError as e:
            raise ValidationError(str(e)) from e
        if len(cases) > MAX_CASES:
            raise ValidationError(f"A dataset can have at most {MAX_CASES} cases")
        ds = EvalDataset(
            organization_id=org_id, name=name.strip()[:200] or "dataset", created_by=user_id,
            cases=[c.model_dump() for c in cases], case_count=len(cases),
        )
        db.add(ds)
        await db.flush()
        return ds

    async def list_datasets(self, db: AsyncSession, org_id: uuid.UUID) -> list[EvalDataset]:
        stmt = (
            select(EvalDataset).where(EvalDataset.organization_id == org_id)
            .order_by(EvalDataset.created_at.desc())
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_dataset(
        self, db: AsyncSession, org_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> EvalDataset:
        ds = (
            await db.execute(
                select(EvalDataset).where(
                    EvalDataset.id == dataset_id, EvalDataset.organization_id == org_id
                )
            )
        ).scalar_one_or_none()
        if ds is None:
            raise NotFoundError("Dataset not found")
        return ds

    async def start_runs(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        dataset_id: uuid.UUID,
        kb_ids: list[uuid.UUID],
        configs: list[RunConfig],
    ) -> list[EvalRun]:
        """One run (and job) per configuration, so strategies/modes can be compared."""
        if not configs or len(configs) > MAX_CONFIGS:
            raise ValidationError(f"Provide between 1 and {MAX_CONFIGS} configurations")
        if not kb_ids:
            raise ValidationError("Select at least one knowledge base")
        await self.get_dataset(db, org_id, dataset_id)
        found = (
            await db.execute(
                select(func.count()).select_from(KnowledgeBase).where(
                    KnowledgeBase.organization_id == org_id, KnowledgeBase.id.in_(kb_ids)
                )
            )
        ).scalar_one()
        if found != len(set(kb_ids)):
            raise NotFoundError("Knowledge base not found")
        runs: list[EvalRun] = []
        for cfg in configs:
            run = EvalRun(
                organization_id=org_id, dataset_id=dataset_id, created_by=user_id,
                knowledge_base_ids=[str(k) for k in kb_ids], config=cfg.model_dump(),
                status="queued",
            )
            db.add(run)
            await db.flush()
            # Evaluations spend LLM budget: a failed run is reported, never silently retried.
            await job_queue.enqueue(
                db, EVAL_KIND, {"run_id": str(run.id)}, org_id=org_id,
                dedupe_key=f"eval:{run.id}", max_attempts=1,
            )
            runs.append(run)
        return runs

    async def list_runs(
        self, db: AsyncSession, org_id: uuid.UUID, limit: int = 50
    ) -> list[EvalRun]:
        stmt = (
            select(EvalRun).where(EvalRun.organization_id == org_id)
            .order_by(EvalRun.created_at.desc()).limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_run(self, db: AsyncSession, org_id: uuid.UUID, run_id: uuid.UUID) -> EvalRun:
        run = (
            await db.execute(
                select(EvalRun).where(EvalRun.id == run_id, EvalRun.organization_id == org_id)
            )
        ).scalar_one_or_none()
        if run is None:
            raise NotFoundError("Run not found")
        return run

    async def compare_runs(
        self, db: AsyncSession, org_id: uuid.UUID, baseline: uuid.UUID, candidate: uuid.UUID
    ) -> list[MetricDelta]:
        a = await self.get_run(db, org_id, baseline)
        b = await self.get_run(db, org_id, candidate)
        if a.status != "succeeded" or b.status != "succeeded":
            raise ValidationError("Both runs must have finished successfully")
        return compare(a.summary or {}, b.summary or {})


def utcnow() -> datetime:
    return datetime.now(UTC)


eval_service = EvalService()
