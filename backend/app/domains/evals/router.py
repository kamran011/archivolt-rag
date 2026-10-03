import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.domains.auth.dependencies import require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.evals.service import RunConfig, eval_service
from app.domains.jobs.setup import worker
from app.evals.report import MetricDelta
from app.models.organization_member import OrgRole

router = APIRouter()
admin_only = require_role(OrgRole.owner, OrgRole.admin)


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    jsonl: str = Field(min_length=1)


class DatasetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    case_count: int
    created_at: datetime


class DatasetDetail(DatasetView):
    cases: list[dict]


class RunCreate(BaseModel):
    dataset_id: uuid.UUID
    knowledge_base_ids: list[uuid.UUID] = Field(min_length=1)
    configs: list[RunConfig] = Field(min_length=1)


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    config: dict
    status: str
    summary: dict | None
    total_cases: int | None
    failed_cases: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class RunDetail(RunView):
    results: list | None


@router.post("/datasets", response_model=DatasetView, status_code=201)
async def create_dataset(
    body: DatasetCreate,
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    ds = await eval_service.create_dataset(
        db, current_user.organization_id, current_user.id, body.name, body.jsonl
    )
    await db.commit()
    return ds


@router.get("/datasets", response_model=list[DatasetView])
async def list_datasets(
    current_user: CurrentUser = Depends(admin_only), db: AsyncSession = Depends(get_db, scope="function")
):
    return await eval_service.list_datasets(db, current_user.organization_id)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(
    dataset_id: uuid.UUID,
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await eval_service.get_dataset(db, current_user.organization_id, dataset_id)


@router.post("/runs", response_model=list[RunView], status_code=202)
async def start_runs(
    body: RunCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Starts one run per configuration (e.g. hybrid vs tree, rag vs cag)."""
    runs = await eval_service.start_runs(
        db, current_user.organization_id, current_user.id, body.dataset_id,
        body.knowledge_base_ids, body.configs,
    )
    await db.commit()
    background_tasks.add_task(worker.run_until_idle)
    return runs


@router.get("/runs", response_model=list[RunView])
async def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await eval_service.list_runs(db, current_user.organization_id, limit)


@router.get("/compare", response_model=list[MetricDelta])
async def compare_runs(
    baseline: uuid.UUID,
    candidate: uuid.UUID,
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await eval_service.compare_runs(db, current_user.organization_id, baseline, candidate)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: uuid.UUID,
    current_user: CurrentUser = Depends(admin_only),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await eval_service.get_run(db, current_user.organization_id, run_id)
