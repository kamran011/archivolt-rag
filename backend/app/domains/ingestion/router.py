import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.domains.auth.dependencies import require_org, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.documents.service import document_service
from app.domains.ingestion.jobs import INGEST_KIND, dedupe_key, enqueue_ingestion
from app.domains.ingestion.schemas import IngestionStatusResponse
from app.domains.jobs.setup import worker
from app.domains.retrieval.access import scope_for
from app.models.job import Job
from app.models.organization_member import OrgRole

router = APIRouter()


@router.post(
    "/documents/{doc_id}/ingest",
    status_code=202,
    dependencies=[Depends(rate_limit("upload", "RATE_LIMIT_UPLOAD_PER_MIN"))],
)
async def trigger_ingestion(
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin, OrgRole.member)
    ),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    # Verify the document belongs to this org (and is visible to the caller) before queueing
    await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    job = await enqueue_ingestion(db, current_user.organization_id, doc_id)
    await db.commit()
    background_tasks.add_task(worker.run_job, job.id)
    return {"status": "queued", "document_id": str(doc_id), "job_id": str(job.id)}


@router.post(
    "/documents/{doc_id}/reprocess",
    status_code=202,
    dependencies=[Depends(rate_limit("upload", "RATE_LIMIT_UPLOAD_PER_MIN"))],
)
async def trigger_reprocess(
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    job = await enqueue_ingestion(db, current_user.organization_id, doc_id, reprocess=True)
    await db.commit()
    background_tasks.add_task(worker.run_job, job.id)
    return {"status": "queued", "document_id": str(doc_id), "job_id": str(job.id)}


@router.get("/documents/{doc_id}/status", response_model=IngestionStatusResponse)
async def get_ingestion_status(
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    doc = await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    job = (
        await db.execute(
            select(Job).where(Job.kind == INGEST_KIND, Job.dedupe_key == dedupe_key(doc.id))
            .order_by(Job.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    return IngestionStatusResponse(
        document_id=str(doc.id),
        status=doc.status.value,
        error_message=doc.error_message,
        job_status=job.status if job else None,
        attempts=job.attempts if job else None,
        max_attempts=job.max_attempts if job else None,
        progress_message=_progress_message(job),
    )


def _progress_message(job: Job | None) -> str | None:
    if job is None:
        return None
    if job.status == "queued" and job.attempts > 0:
        return f"retrying (attempt {job.attempts + 1} of {job.max_attempts})"
    if job.status == "queued":
        return "waiting to start"
    if job.status == "running":
        return f"processing (attempt {job.attempts} of {job.max_attempts})"
    return None
