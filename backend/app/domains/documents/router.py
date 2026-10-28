import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.domains.auth.dependencies import require_org, require_role
from app.domains.auth.schemas import CurrentUser
from app.domains.documents.schemas import (
    ChunkPage,
    ChunkView,
    DocumentDetailResponse,
    DocumentResponse,
    DocumentSummaries,
    DocumentTree,
    DocumentUpdate,
    SignedUrlResponse,
    SummaryView,
)
from app.domains.documents.service import document_service
from app.domains.ingestion.jobs import enqueue_ingestion
from app.domains.jobs.setup import worker
from app.domains.retrieval.access import scope_for
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
    restricted: bool = Form(False),
    tags: str = Form(""),
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin, OrgRole.member)
    ),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    doc = await document_service.upload(
        db,
        current_user.organization_id,
        kb_id,
        file,
        uploaded_by=current_user.id,
        restricted=restricted,
        tags=[t for t in tags.split(",") if t.strip()],
        scope=scope_for(current_user),
    )
    # The ingestion job is created in the same transaction as the document, so neither can
    # exist without the other. Commit before running so the job's own session sees both.
    job = await enqueue_ingestion(db, current_user.organization_id, doc.id)
    await db.commit()

    # Run it right away; if this process dies or the attempt fails transiently, the durable
    # job row is retried/reclaimed by the worker.
    background_tasks.add_task(worker.run_job, job.id)

    return DocumentResponse.model_validate(doc)


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    kb_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    docs = await document_service.list(
        db, current_user.organization_id, kb_id, scope=scope_for(current_user)
    )
    return [DocumentResponse.model_validate(d) for d in docs]


@router.get("/{doc_id}/chunks", response_model=ChunkPage)
async def list_document_chunks(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """The chunks a document was split into (what retrieval actually indexes)."""
    total, items = await document_service.list_chunks(
        db, current_user.organization_id, doc_id, limit, offset, scope=scope_for(current_user)
    )
    return ChunkPage(total=total, items=[ChunkView(**i) for i in items])


@router.get("/{doc_id}/tree", response_model=DocumentTree)
async def get_document_tree(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """The heading outline built at ingestion (used for tree navigation)."""
    doc = await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    nodes = (doc.parsing_metadata or {}).get("tree") or []
    return DocumentTree(document_id=doc.id, nodes=nodes)


@router.get("/{doc_id}/summaries", response_model=DocumentSummaries)
async def get_document_summaries(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Navigation summaries (document + sections). Model-written; not evidence."""
    rows = await document_service.list_summaries(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    return DocumentSummaries(
        document_id=doc_id,
        items=[
            SummaryView(level=r.level, node_id=r.node_id, title=r.title, summary=r.summary)
            for r in rows
        ],
    )


@router.get("/{doc_id}", response_model=DocumentDetailResponse)
async def get_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    doc = await document_service.get(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    return DocumentDetailResponse.model_validate(doc)


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    data: DocumentUpdate,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    doc = await document_service.update(
        db, current_user.organization_id, doc_id, data, scope=scope_for(current_user)
    )
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
    db: AsyncSession = Depends(get_db, scope="function"),
):
    new_doc = await document_service.create_new_version(
        db,
        current_user.organization_id,
        doc_id,
        file,
        uploaded_by=current_user.id,
        scope=scope_for(current_user),
    )
    job = await enqueue_ingestion(db, current_user.organization_id, new_doc.id)
    await db.commit()
    background_tasks.add_task(worker.run_job, job.id)
    return DocumentResponse.model_validate(new_doc)


@router.get("/{doc_id}/versions", response_model=list[DocumentResponse])
async def list_document_versions(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    versions = await document_service.list_versions(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    return [DocumentResponse.model_validate(v) for v in versions]


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(
        require_role(OrgRole.owner, OrgRole.admin)
    ),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    await document_service.delete(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )


@router.get("/{doc_id}/download", response_model=SignedUrlResponse)
async def download_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_org),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    url = await document_service.get_signed_url(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )
    return SignedUrlResponse(url=url, expires_in=3600)


class AccessGrant(BaseModel):
    user_id: uuid.UUID


@router.get("/{doc_id}/access", response_model=list[uuid.UUID])
async def list_document_access(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Users explicitly granted access to a restricted document."""
    return await document_service.list_access(
        db, current_user.organization_id, doc_id, scope=scope_for(current_user)
    )


@router.post("/{doc_id}/access", status_code=204)
async def grant_document_access(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    body: AccessGrant,
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    await document_service.grant_access(
        db, current_user.organization_id, doc_id, body.user_id, scope=scope_for(current_user)
    )


@router.delete("/{doc_id}/access/{user_id}", status_code=204)
async def revoke_document_access(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_role(OrgRole.owner, OrgRole.admin)),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    await document_service.revoke_access(
        db, current_user.organization_id, doc_id, user_id, scope=scope_for(current_user)
    )
