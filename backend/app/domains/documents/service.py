import uuid
from datetime import UTC, datetime

import structlog
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.domains.documents.schemas import DocumentUpdate
from app.domains.documents.storage import storage_service
from app.domains.knowledge_bases.service import kb_service
from app.models.document import AuthorityTier, Document, DocumentStatus, FileType

logger = structlog.get_logger()

ALLOWED_EXTENSIONS: dict[str, FileType] = {
    ".pdf": FileType.pdf,
    ".docx": FileType.docx,
    ".md": FileType.md,
    ".markdown": FileType.md,
    ".txt": FileType.txt,
    ".html": FileType.html,
    ".htm": FileType.html,
    ".csv": FileType.csv,
    ".json": FileType.json,
}


class DocumentService:
    def _validate_upload(self, file: UploadFile) -> FileType:
        if not file.filename:
            raise ValidationError("File must have a name")

        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        file_type = ALLOWED_EXTENSIONS.get(ext)
        if not file_type:
            allowed = ", ".join(ALLOWED_EXTENSIONS.keys())
            raise ValidationError(f"Unsupported file type '{ext}'. Allowed: {allowed}")

        return file_type

    async def upload(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
        file: UploadFile,
        uploaded_by: uuid.UUID | None = None,
        authority_tier: AuthorityTier = AuthorityTier.standard,
    ) -> Document:
        # Verify KB exists and belongs to org
        await kb_service.get(db, org_id, kb_id)

        document = await self._store_and_create(
            db,
            org_id=org_id,
            kb_id=kb_id,
            file=file,
            uploaded_by=uploaded_by,
            version=1,
            supersedes_document_id=None,
            authority_tier=authority_tier,
        )

        await kb_service.increment_document_count(db, kb_id, delta=1)
        return document

    async def create_new_version(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        file: UploadFile,
        uploaded_by: uuid.UUID | None = None,
        effective_date: datetime | None = None,
    ) -> Document:
        """Uploads a new version of an existing document. The prior version is
        marked superseded and excluded from retrieval by default (freshness),
        but remains queryable for historical questions via
        RetrievalFilters.include_superseded."""
        previous = await self.get(db, org_id, doc_id)

        new_document = await self._store_and_create(
            db,
            org_id=org_id,
            kb_id=previous.knowledge_base_id,
            file=file,
            uploaded_by=uploaded_by,
            version=previous.version + 1,
            supersedes_document_id=previous.id,
            authority_tier=previous.authority_tier,
            effective_date=effective_date,
        )

        previous.is_current = False
        previous.superseded_at = datetime.now(UTC)
        await db.flush()

        await kb_service.increment_document_count(db, previous.knowledge_base_id, delta=1)

        logger.info(
            "document_version_created",
            previous_doc_id=str(previous.id),
            new_doc_id=str(new_document.id),
            version=new_document.version,
        )
        return new_document

    async def list_versions(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> list[Document]:
        """Returns the full version chain (oldest to newest) for the document family."""
        anchor = await self.get(db, org_id, doc_id)

        # Walk backward to find the root of the version chain
        root_id = anchor.id
        current = anchor
        while current.supersedes_document_id:
            parent = await db.get(Document, current.supersedes_document_id)
            if not parent:
                break
            root_id = parent.id
            current = parent

        # Collect the full chain forward from the root
        chain: list[Document] = []
        node: Document | None = await db.get(Document, root_id)
        while node:
            chain.append(node)
            stmt = select(Document).where(Document.supersedes_document_id == node.id)
            result = await db.execute(stmt)
            node = result.scalar_one_or_none()

        return chain

    async def update(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        data: DocumentUpdate,
    ) -> Document:
        doc = await self.get(db, org_id, doc_id)
        if data.authority_tier is not None:
            doc.authority_tier = data.authority_tier
        if data.effective_date is not None:
            doc.effective_date = data.effective_date
        await db.flush()
        return doc

    async def _store_and_create(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
        file: UploadFile,
        uploaded_by: uuid.UUID | None,
        version: int,
        supersedes_document_id: uuid.UUID | None,
        authority_tier: AuthorityTier,
        effective_date: datetime | None = None,
    ) -> Document:
        file_type = self._validate_upload(file)

        content = await file.read()
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(content) > max_bytes:
            raise ValidationError(
                f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB"
            )
        if len(content) == 0:
            raise ValidationError("File is empty")

        doc_id = uuid.uuid4()
        storage_path = storage_service.build_path(org_id, kb_id, doc_id, file.filename)

        await storage_service.upload_file(
            storage_path, content, file.content_type or "application/octet-stream"
        )

        document = Document(
            id=doc_id,
            organization_id=org_id,
            knowledge_base_id=kb_id,
            title=file.filename.rsplit(".", 1)[0],
            file_name=file.filename,
            file_type=file_type,
            file_size=len(content),
            storage_path=storage_path,
            status=DocumentStatus.pending,
            uploaded_by=uploaded_by,
            version=version,
            is_current=True,
            supersedes_document_id=supersedes_document_id,
            authority_tier=authority_tier,
            effective_date=effective_date,
        )
        db.add(document)
        await db.flush()

        logger.info(
            "document_stored",
            doc_id=str(doc_id),
            kb_id=str(kb_id),
            file_type=file_type.value,
            size=len(content),
            version=version,
        )
        return document

    async def get(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> Document:
        stmt = select(Document).where(
            Document.id == doc_id,
            Document.organization_id == org_id,
        )
        result = await db.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            raise NotFoundError(f"Document {doc_id} not found")
        return doc

    async def list(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(
                Document.organization_id == org_id,
                Document.knowledge_base_id == kb_id,
            )
            .order_by(Document.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def delete(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
    ) -> None:
        doc = await self.get(db, org_id, doc_id)
        await storage_service.delete_file(doc.storage_path)
        await db.delete(doc)  # cascades to chunks
        await kb_service.increment_document_count(db, doc.knowledge_base_id, delta=-1)
        await db.flush()

    async def get_signed_url(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        expires_in: int = 3600,
    ) -> str:
        doc = await self.get(db, org_id, doc_id)
        return await storage_service.get_signed_url(doc.storage_path, expires_in)

    async def update_status(
        self,
        db: AsyncSession,
        doc_id: uuid.UUID,
        status: DocumentStatus,
        error_message: str | None = None,
    ) -> None:
        doc = await db.get(Document, doc_id)
        if doc:
            doc.status = status
            if error_message is not None:
                doc.error_message = error_message
            await db.flush()


document_service = DocumentService()
