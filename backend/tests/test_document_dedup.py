"""Duplicate-upload guard: documents.file_hash + DocumentService._find_duplicate_file /
_store_and_create. Runs against real (in-memory SQLite) tables, same pattern as
test_cross_tenant_isolation.py, so this proves the query-level behavior, not just that the
code "looks right"."""

import hashlib
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import ValidationError
from app.domains.documents.connectors.base import RawFile
from app.domains.documents.service import DocumentService
from app.domains.retrieval.access import SYSTEM_SCOPE, AccessScope
from app.models.base import Base
from app.models.document import AuthorityTier, Document, DocumentAccess, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization

CONTENT_A = b"Refund window is 30 days."
CONTENT_B = b"Something else entirely."
HASH_A = hashlib.sha256(CONTENT_A).hexdigest()


@pytest_asyncio.fixture
async def sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Organization.__table__,
        KnowledgeBase.__table__,
        Document.__table__,
        DocumentAccess.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def make_document(
    org_id,
    kb_id,
    *,
    title="Doc",
    file_hash=HASH_A,
    is_current=True,
    status=DocumentStatus.ready,
    restricted=False,
    uploaded_by=None,
    supersedes_document_id=None,
) -> Document:
    return Document(
        id=uuid.uuid4(),
        organization_id=org_id,
        knowledge_base_id=kb_id,
        title=title,
        file_name=f"{title}.txt",
        file_type="txt",
        file_size=len(CONTENT_A),
        file_hash=file_hash,
        storage_path=f"{org_id}/{kb_id}/{title}",
        status=status,
        uploaded_by=uploaded_by,
        version=1,
        is_current=is_current,
        supersedes_document_id=supersedes_document_id,
        authority_tier=AuthorityTier.standard,
        restricted=restricted,
        tags=[],
    )


@pytest_asyncio.fixture
async def seeded(sqlite_session):
    org_id, kb_id = uuid.uuid4(), uuid.uuid4()
    sqlite_session.add(Organization(id=org_id, name="Org", slug="org"))
    sqlite_session.add(KnowledgeBase(id=kb_id, organization_id=org_id, name="KB"))
    await sqlite_session.flush()
    return org_id, kb_id


@pytest.mark.asyncio
async def test_finds_an_exact_match_in_the_same_kb(sqlite_session, seeded):
    org_id, kb_id = seeded
    existing = make_document(org_id, kb_id, title="Refund Policy")
    sqlite_session.add(existing)
    await sqlite_session.flush()

    service = DocumentService()
    match = await service._find_duplicate_file(sqlite_session, org_id, kb_id, HASH_A, SYSTEM_SCOPE)
    assert match is not None and match.id == existing.id


@pytest.mark.asyncio
async def test_no_match_for_a_different_hash(sqlite_session, seeded):
    org_id, kb_id = seeded
    sqlite_session.add(make_document(org_id, kb_id))
    await sqlite_session.flush()

    service = DocumentService()
    other_hash = hashlib.sha256(CONTENT_B).hexdigest()
    match = await service._find_duplicate_file(
        sqlite_session, org_id, kb_id, other_hash, SYSTEM_SCOPE
    )
    assert match is None


@pytest.mark.asyncio
async def test_superseded_version_does_not_count_as_a_duplicate(sqlite_session, seeded):
    org_id, kb_id = seeded
    sqlite_session.add(make_document(org_id, kb_id, is_current=False))
    await sqlite_session.flush()

    service = DocumentService()
    match = await service._find_duplicate_file(sqlite_session, org_id, kb_id, HASH_A, SYSTEM_SCOPE)
    assert match is None


@pytest.mark.asyncio
async def test_a_failed_document_does_not_count_as_a_duplicate(sqlite_session, seeded):
    org_id, kb_id = seeded
    sqlite_session.add(make_document(org_id, kb_id, status=DocumentStatus.failed))
    await sqlite_session.flush()

    service = DocumentService()
    match = await service._find_duplicate_file(sqlite_session, org_id, kb_id, HASH_A, SYSTEM_SCOPE)
    assert match is None


@pytest.mark.asyncio
async def test_exclude_document_id_skips_the_version_being_superseded(sqlite_session, seeded):
    org_id, kb_id = seeded
    existing = make_document(org_id, kb_id)
    sqlite_session.add(existing)
    await sqlite_session.flush()

    service = DocumentService()
    match = await service._find_duplicate_file(
        sqlite_session, org_id, kb_id, HASH_A, SYSTEM_SCOPE, exclude_document_id=existing.id
    )
    assert match is None


@pytest.mark.asyncio
async def test_a_restricted_duplicate_is_invisible_so_the_upload_proceeds(sqlite_session, seeded):
    """The uploader must not learn a hidden document exists: a restricted match they cannot
    see is treated as no match at all, not as a different kind of rejection."""
    org_id, kb_id = seeded
    other_uploader = uuid.uuid4()
    sqlite_session.add(
        make_document(org_id, kb_id, restricted=True, uploaded_by=other_uploader)
    )
    await sqlite_session.flush()

    service = DocumentService()
    unrelated_caller = AccessScope(user_id=uuid.uuid4(), is_admin=False)
    match = await service._find_duplicate_file(
        sqlite_session, org_id, kb_id, HASH_A, unrelated_caller
    )
    assert match is None


@pytest.mark.asyncio
async def test_an_admin_sees_a_restricted_duplicate(sqlite_session, seeded):
    org_id, kb_id = seeded
    other_uploader = uuid.uuid4()
    existing = make_document(org_id, kb_id, restricted=True, uploaded_by=other_uploader)
    sqlite_session.add(existing)
    await sqlite_session.flush()

    service = DocumentService()
    admin_scope = AccessScope(user_id=uuid.uuid4(), is_admin=True)
    match = await service._find_duplicate_file(sqlite_session, org_id, kb_id, HASH_A, admin_scope)
    assert match is not None and match.id == existing.id


@pytest.mark.asyncio
async def test_same_hash_in_a_different_kb_is_not_a_duplicate(sqlite_session, seeded):
    org_id, kb_id = seeded
    other_kb_id = uuid.uuid4()
    sqlite_session.add(KnowledgeBase(id=other_kb_id, organization_id=org_id, name="Other KB"))
    sqlite_session.add(make_document(org_id, other_kb_id))
    await sqlite_session.flush()

    service = DocumentService()
    match = await service._find_duplicate_file(sqlite_session, org_id, kb_id, HASH_A, SYSTEM_SCOPE)
    assert match is None


class _FakeUploadFile:
    """Minimal stand-in: _store_and_create only reads .filename and .content_type."""

    def __init__(self, filename: str, content_type: str = "text/plain"):
        self.filename = filename
        self.content_type = content_type


@pytest.mark.asyncio
async def test_store_and_create_rejects_a_duplicate_before_touching_storage(
    sqlite_session, seeded, monkeypatch
):
    org_id, kb_id = seeded
    sqlite_session.add(make_document(org_id, kb_id, title="Refund Policy"))
    await sqlite_session.flush()

    service = DocumentService()
    async def _fetch(*a, **kw):
        return RawFile(filename="refund-policy.txt", content=CONTENT_A, content_type="text/plain")

    monkeypatch.setattr(service._connector, "fetch", _fetch)
    upload_called = False

    async def _should_not_run(*a, **kw):
        nonlocal upload_called
        upload_called = True

    monkeypatch.setattr(
        "app.domains.documents.service.storage_service.upload_file", _should_not_run
    )

    with pytest.raises(ValidationError, match="already in this knowledge base as 'Refund Policy'"):
        await service._store_and_create(
            sqlite_session,
            org_id=org_id,
            kb_id=kb_id,
            file=_FakeUploadFile("refund-policy.txt"),
            uploaded_by=None,
            version=1,
            supersedes_document_id=None,
            authority_tier=AuthorityTier.standard,
            scope=SYSTEM_SCOPE,
        )
    assert upload_called is False


@pytest.mark.asyncio
async def test_identical_new_version_is_rejected_with_its_own_message(
    sqlite_session, seeded, monkeypatch
):
    org_id, kb_id = seeded
    previous = make_document(org_id, kb_id, title="Refund Policy")
    sqlite_session.add(previous)
    await sqlite_session.flush()

    service = DocumentService()

    async def _fetch(*a, **kw):
        return RawFile(
            filename="refund-policy-v2.txt", content=CONTENT_A, content_type="text/plain"
        )

    monkeypatch.setattr(service._connector, "fetch", _fetch)

    with pytest.raises(ValidationError, match="identical to the current version"):
        await service._store_and_create(
            sqlite_session,
            org_id=org_id,
            kb_id=kb_id,
            file=_FakeUploadFile("refund-policy-v2.txt"),
            uploaded_by=None,
            version=2,
            supersedes_document_id=previous.id,
            authority_tier=AuthorityTier.standard,
            scope=SYSTEM_SCOPE,
        )


@pytest.mark.asyncio
async def test_a_genuinely_new_version_is_accepted(sqlite_session, seeded, monkeypatch):
    org_id, kb_id = seeded
    previous = make_document(org_id, kb_id, title="Refund Policy")
    sqlite_session.add(previous)
    await sqlite_session.flush()

    service = DocumentService()

    async def _fetch(*a, **kw):
        return RawFile(
            filename="refund-policy-v2.txt", content=CONTENT_B, content_type="text/plain"
        )

    async def _upload_file(*a, **kw):
        return None

    monkeypatch.setattr(service._connector, "fetch", _fetch)
    monkeypatch.setattr(
        "app.domains.documents.service.storage_service.upload_file", _upload_file
    )
    monkeypatch.setattr(
        "app.domains.documents.service.storage_service.build_path",
        lambda *a, **kw: "some/path",
    )

    new_doc = await service._store_and_create(
        sqlite_session,
        org_id=org_id,
        kb_id=kb_id,
        file=_FakeUploadFile("refund-policy-v2.txt"),
        uploaded_by=None,
        version=2,
        supersedes_document_id=previous.id,
        authority_tier=AuthorityTier.standard,
        scope=SYSTEM_SCOPE,
    )
    assert new_doc.file_hash == hashlib.sha256(CONTENT_B).hexdigest()
