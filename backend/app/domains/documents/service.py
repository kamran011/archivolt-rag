import builtins
import hashlib
import uuid
from datetime import datetime

import structlog
from fastapi import UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.domains.documents.connectors.registry import get_knowledge_connector
from app.domains.documents.schemas import DocumentUpdate
from app.domains.documents.storage import storage_service
from app.domains.documents.upload_safety import sanitize_filename, sniff_content
from app.domains.knowledge_bases.service import kb_service
from app.domains.retrieval.access import AccessScope, visible_document_clause
from app.models.chunk import Chunk
from app.models.document import (
    AuthorityTier,
    Document,
    DocumentAccess,
    DocumentStatus,
    FileType,
)
from app.models.organization_member import OrganizationMember
from app.models.summary import DocumentSummary

logger = structlog.get_logger()


async def _evict_cached_answers(*, doc_ids=(), kb_ids=()) -> None:
    """Invalidate-on-write for the answer cache (reverse indexes: document/KB -> entries)."""
    from app.domains.rag import response_cache

    for doc_id in doc_ids:
        await response_cache.invalidate_document(doc_id)
    for kb_id in kb_ids:
        await response_cache.invalidate_kb(kb_id)

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
    ".png": FileType.image,
    ".jpg": FileType.image,
    ".jpeg": FileType.image,
    ".webp": FileType.image,
}


class DocumentService:
    def __init__(self) -> None:
        self._connector = get_knowledge_connector()

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
        restricted: bool = False,
        tags: builtins.list[str] | None = None,
        *,
        scope: AccessScope,
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
            restricted=restricted,
            tags=tags,
            scope=scope,
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
        *,
        scope: AccessScope,
    ) -> Document:
        """Uploads a new version of an existing document. The prior version stays
        current until the new one is ingested successfully; ingestion then marks it
        superseded and excludes it from retrieval by default (freshness), though it
        remains queryable for historical questions via
        RetrievalFilters.include_superseded. A failed ingestion leaves it current."""
        previous = await self.get(db, org_id, doc_id, scope=scope)

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
            scope=scope,
        )
        # A new version must not become more visible than the one it replaces.
        new_document.tags = list(previous.tags or [])
        new_document.restricted = previous.restricted
        grants = await db.execute(
            select(DocumentAccess.user_id).where(DocumentAccess.document_id == previous.id)
        )
        for (grantee,) in grants.all():
            db.add(
                DocumentAccess(organization_id=org_id, document_id=new_document.id, user_id=grantee)
            )

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
        *,
        scope: AccessScope,
    ) -> list[Document]:
        """Returns the full version chain (oldest to newest) for the document family.
        Versions share their access settings (see create_new_version), so checking the
        anchor covers the chain."""
        anchor = await self.get(db, org_id, doc_id, scope=scope)

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
        *,
        scope: AccessScope,
    ) -> Document:
        doc = await self.get(db, org_id, doc_id, scope=scope)
        if data.tags is not None:
            doc.tags = sorted({t.strip() for t in data.tags if t.strip()})
        if data.restricted is not None:
            doc.restricted = data.restricted
        if data.authority_tier is not None:
            doc.authority_tier = data.authority_tier
        if data.effective_date is not None:
            doc.effective_date = data.effective_date
        await db.flush()
        await _evict_cached_answers(doc_ids=[doc.id])
        return doc

    async def _find_duplicate_file(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_id: uuid.UUID,
        file_hash: str,
        scope: AccessScope | None,
        exclude_document_id: uuid.UUID | None = None,
    ) -> Document | None:
        """The current, non-failed document in this KB with identical bytes, if the caller
        can see it. A match the caller cannot see (a restricted document) is treated as no
        match: `visible_document_clause` excludes it from the query, so the upload proceeds
        rather than revealing that a hidden document exists."""
        stmt = select(Document).where(
            Document.organization_id == org_id,
            Document.knowledge_base_id == kb_id,
            Document.file_hash == file_hash,
            Document.is_current.is_(True),
            Document.status != DocumentStatus.failed,
            visible_document_clause(scope),
        )
        if exclude_document_id is not None:
            stmt = stmt.where(Document.id != exclude_document_id)
        result = await db.execute(stmt)
        return result.scalars().first()

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
        restricted: bool = False,
        tags: builtins.list[str] | None = None,
        scope: AccessScope | None = None,
    ) -> Document:
        file_type = self._validate_upload(file)
        safe_name = sanitize_filename(file.filename)

        raw = await self._connector.fetch(
            file,
            max_bytes=settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024,
            max_mb=settings.MAX_UPLOAD_SIZE_MB,
        )
        content = raw.content
        if len(content) == 0:
            raise ValidationError("File is empty")
        sniff_content(content, file_type)

        file_hash = hashlib.sha256(content).hexdigest()

        if supersedes_document_id is not None:
            previous = await db.get(Document, supersedes_document_id)
            if previous and previous.file_hash == file_hash:
                raise ValidationError("This file is identical to the current version.")

        duplicate = await self._find_duplicate_file(
            db, org_id, kb_id, file_hash, scope, exclude_document_id=supersedes_document_id
        )
        if duplicate:
            raise ValidationError(
                f"This file is already in this knowledge base as '{duplicate.title}'."
            )

        doc_id = uuid.uuid4()
        storage_path = storage_service.build_path(org_id, kb_id, doc_id, safe_name)

        # Only touch storage once every check has passed, so a rejected upload leaves no
        # orphan file behind.
        await storage_service.upload_file(
            storage_path, content, file.content_type or "application/octet-stream"
        )

        document = Document(
            id=doc_id,
            organization_id=org_id,
            knowledge_base_id=kb_id,
            title=safe_name.rsplit(".", 1)[0],
            file_name=safe_name,
            file_type=file_type,
            file_size=len(content),
            file_hash=file_hash,
            storage_path=storage_path,
            status=DocumentStatus.pending,
            uploaded_by=uploaded_by,
            version=version,
            is_current=True,
            supersedes_document_id=supersedes_document_id,
            authority_tier=authority_tier,
            effective_date=effective_date,
            restricted=restricted,
            tags=sorted({t.strip() for t in (tags or []) if t.strip()}),
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
        *,
        scope: AccessScope,
    ) -> Document:
        """Org-scoped fetch that also enforces document-level access. `scope` is required
        so a caller cannot forget it; internal callers pass SYSTEM_SCOPE explicitly. A
        restricted document the scope cannot see looks like it does not exist."""
        stmt = select(Document).where(
            Document.id == doc_id,
            Document.organization_id == org_id,
            visible_document_clause(scope),
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
        *,
        scope: AccessScope,
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(
                Document.organization_id == org_id,
                Document.knowledge_base_id == kb_id,
                visible_document_clause(scope),
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
        *,
        scope: AccessScope,
    ) -> None:
        doc = await self.get(db, org_id, doc_id, scope=scope)
        await storage_service.delete_file(doc.storage_path)
        await db.delete(doc)  # cascades to chunks
        await kb_service.increment_document_count(db, doc.knowledge_base_id, delta=-1)
        await db.flush()
        await _evict_cached_answers(doc_ids=[doc.id], kb_ids=[doc.knowledge_base_id])

    async def list_chunks(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        limit: int,
        offset: int,
        *,
        scope: AccessScope,
    ) -> tuple[int, builtins.list[dict]]:  # `list` is shadowed by the method above
        """Chunks of a document (org-scoped), without loading the embedding vectors."""
        await self.get(db, org_id, doc_id, scope=scope)
        base = (Chunk.document_id == doc_id, Chunk.organization_id == org_id)
        total = (
            await db.execute(select(func.count()).select_from(Chunk).where(*base))
        ).scalar_one()
        rows = await db.execute(
            select(
                Chunk.id,
                Chunk.chunk_index,
                Chunk.token_count,
                Chunk.content,
                Chunk.metadata_,
                Chunk.embedding.is_not(None).label("has_embedding"),
            )
            .where(*base)
            .order_by(Chunk.chunk_index)
            .limit(limit)
            .offset(offset)
        )
        return total, [
            {
                "id": r.id,
                "chunk_index": r.chunk_index,
                "token_count": r.token_count,
                "content": r.content,
                "metadata": r.metadata_,
                "has_embedding": r.has_embedding,
            }
            for r in rows
        ]

    async def list_summaries(
        self, db: AsyncSession, org_id: uuid.UUID, doc_id: uuid.UUID, *, scope: AccessScope
    ) -> builtins.list[DocumentSummary]:
        await self.get(db, org_id, doc_id, scope=scope)
        rows = await db.execute(
            select(DocumentSummary)
            .where(DocumentSummary.document_id == doc_id, DocumentSummary.organization_id == org_id)
            .order_by(DocumentSummary.level.desc(), DocumentSummary.node_id)
        )
        return list(rows.scalars().all())

    async def get_signed_url(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        expires_in: int = 3600,
        *,
        scope: AccessScope,
    ) -> str:
        doc = await self.get(db, org_id, doc_id, scope=scope)
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



    # --- document-level access grants (managed by owners/admins) ---------------------

    async def list_access(
        self, db: AsyncSession, org_id: uuid.UUID, doc_id: uuid.UUID, *, scope: AccessScope
    ) -> builtins.list[uuid.UUID]:
        await self.get(db, org_id, doc_id, scope=scope)
        rows = await db.execute(
            select(DocumentAccess.user_id).where(
                DocumentAccess.document_id == doc_id, DocumentAccess.organization_id == org_id
            )
        )
        return [r[0] for r in rows.all()]

    async def grant_access(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        scope: AccessScope,
    ) -> None:
        await self.get(db, org_id, doc_id, scope=scope)
        member = await db.execute(
            select(OrganizationMember.id).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        if member.first() is None:
            # Grants only make sense inside the org; also avoids probing other orgs' users.
            raise ValidationError("User is not a member of this organization")
        existing = await db.execute(
            select(DocumentAccess.id).where(
                DocumentAccess.document_id == doc_id, DocumentAccess.user_id == user_id
            )
        )
        if existing.first() is None:
            db.add(DocumentAccess(organization_id=org_id, document_id=doc_id, user_id=user_id))
            await db.flush()
            await _evict_cached_answers(doc_ids=[doc_id])

    async def revoke_access(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        doc_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        scope: AccessScope,
    ) -> None:
        await self.get(db, org_id, doc_id, scope=scope)
        await db.execute(
            delete(DocumentAccess).where(
                DocumentAccess.document_id == doc_id,
                DocumentAccess.organization_id == org_id,
                DocumentAccess.user_id == user_id,
            )
        )
        await _evict_cached_answers(doc_ids=[doc_id])


document_service = DocumentService()
