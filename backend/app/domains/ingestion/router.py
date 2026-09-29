import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.domains.auth.dependencies import require_org, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.documents.service import document_service
from app.domains.ingestion.background import run_ingestion
from app.domains.ingestion.schemas import IngestionStatusResponse
from app.domains.retrieval.access import scope_for
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
    db: AsyncSession = Depends(get_db),
):
    # Verify the document belongs to this org before dispatching
    await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    background_tasks.add_task(run_ingestion, doc_id)
    return {"status": "queued", "document_id": str(doc_id)}


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
    db: AsyncSession = Depends(get_db),
):
    await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )

    background_tasks.add_task(run_ingestion, doc_id, True)
    return {"status": "queued", "document_id": str(doc_id)}


@router.get("/documents/{doc_id}/status", response_model=IngestionStatusResponse)
async def get_ingestion_status(
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    return IngestionStatusResponse(
        document_id=str(doc.id),
        status=doc.status.value,
        error_message=doc.error_message,
    )
