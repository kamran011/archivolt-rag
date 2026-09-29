import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.domains.auth.dependencies import require_org, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.documents.schemas import (
    DocumentDetailResponse,
    DocumentResponse,
    DocumentUpdate,
    SignedUrlResponse,
)
from app.domains.documents.service import document_service
from app.domains.ingestion.background import run_ingestion
from app.models.organization_member import OrgRole

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("upload", "RATE_LIMIT_UPLOAD_PER_MIN"))],
)
async def upload_document(
    kb_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin, OrgRole.member)
    ),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.upload(
        db, current_user.organization_id, kb_id, file, uploaded_by=current_user.id
    )
    # Commit explicitly so the row is visible to the background task's own
    # DB session, regardless of dependency-cleanup-vs-background-task ordering.
    await db.commit()

    background_tasks.add_task(run_ingestion, doc.id)

    return DocumentResponse.model_validate(doc)


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    docs = await document_service.list(db, current_user.organization_id, kb_id)
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get(db, current_user.organization_id, doc_id)
    return DocumentDetailResponse.model_validate(doc)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    data: DocumentUpdate,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.update(db, current_user.organization_id, doc_id, data)
    return DocumentResponse.model_validate(doc)


@router.post(
    "/{doc_id}/versions",
    response_model=DocumentResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("upload", "RATE_LIMIT_UPLOAD_PER_MIN"))],
)
async def create_document_version(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin, OrgRole.member)
    ),
    db: AsyncSession = Depends(get_db),
):
    new_doc = await document_service.create_new_version(
        db, current_user.organization_id, doc_id, file, uploaded_by=current_user.id
    )
    await db.commit()
    background_tasks.add_task(run_ingestion, new_doc.id)
    return DocumentResponse.model_validate(new_doc)


@router.get("/{doc_id}/versions", response_model=list[DocumentResponse])
async def list_document_versions(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    versions = await document_service.list_versions(db, current_user.organization_id, doc_id)
    return [DocumentResponse.model_validate(v) for v in versions]


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db),
):
    await document_service.delete(db, current_user.organization_id, doc_id)


@router.get("/{doc_id}/download", response_model=SignedUrlResponse)
async def download_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db),
):
    url = await document_service.get_signed_url(db, current_user.organization_id, doc_id)
    return SignedUrlResponse(url=url, expires_in=3600)
