import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.documents.service import DocumentService
from app.domains.retrieval.access import SYSTEM_SCOPE
from app.models.document import AuthorityTier, Document, FileType


def make_document(
    doc_id: uuid.UUID,
    org_id: uuid.UUID,
    version: int = 1,
    supersedes_document_id: uuid.UUID | None = None,
    is_current: bool = True,
) -> Document:
    return Document(
        id=doc_id,
        organization_id=org_id,
        knowledge_base_id=uuid.uuid4(),
        title="Policy",
        file_name="policy.pdf",
        file_type=FileType.pdf,
        file_size=100,
        storage_path="x/y/z",
        version=version,
        is_current=is_current,
        supersedes_document_id=supersedes_document_id,
        authority_tier=AuthorityTier.standard,
    )


@pytest.mark.asyncio
async def test_create_new_version_keeps_previous_current_until_ingested():
    org_id = uuid.uuid4()
    previous_id = uuid.uuid4()
    new_id = uuid.uuid4()
    previous = make_document(previous_id, org_id, version=1)
    new_doc = make_document(new_id, org_id, version=2, supersedes_document_id=previous_id)

    service = DocumentService()
    db = AsyncMock()

    with patch.object(service, "get", new=AsyncMock(return_value=previous)), patch.object(
        service, "_store_and_create", new=AsyncMock(return_value=new_doc)
    ), patch(
        "app.domains.documents.service.kb_service.increment_document_count",
        new=AsyncMock(),
    ):
        grants = MagicMock()
        grants.all.return_value = []
        db.execute = AsyncMock(return_value=grants)
        result = await service.create_new_version(
            db, org_id, previous_id, file=MagicMock(), scope=SYSTEM_SCOPE
        )

    assert result.id == new_id
    assert result.version == 2
    assert result.supersedes_document_id == previous_id
    # Superseding happens only after the new version is ingested successfully.
    assert previous.is_current is True
    assert previous.superseded_at is None


@pytest.mark.asyncio
async def test_successful_ingestion_supersedes_previous_version():
    from app.domains.ingestion.service import IngestionService

    org_id, previous_id = uuid.uuid4(), uuid.uuid4()
    previous = make_document(previous_id, org_id, version=1)
    new_doc = make_document(uuid.uuid4(), org_id, version=2, supersedes_document_id=previous_id)
    db = AsyncMock()
    db.get = AsyncMock(return_value=previous)

    await IngestionService()._supersede_previous(db, new_doc)
    assert previous.is_current is False and previous.superseded_at is not None

    # A first version supersedes nothing.
    db.get.reset_mock()
    await IngestionService()._supersede_previous(db, previous)
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_list_versions_returns_full_chain_oldest_to_newest():
    org_id = uuid.uuid4()
    v1_id, v2_id, v3_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    v1 = make_document(v1_id, org_id, version=1, is_current=False)
    v2 = make_document(v2_id, org_id, version=2, supersedes_document_id=v1_id, is_current=False)
    v3 = make_document(v3_id, org_id, version=3, supersedes_document_id=v2_id, is_current=True)

    docs_by_id = {v1_id: v1, v2_id: v2, v3_id: v3}

    service = DocumentService()
    db = AsyncMock()

    async def fake_get(model, doc_id):
        return docs_by_id.get(doc_id)

    # list_versions walks the forward chain sequentially (root -> ... -> tip),
    # issuing one "find child of this node" query per step. The traversal
    # order is deterministic, so a simple queue of expected results is a
    # faithful (and much less brittle) stand-in for inspecting compiled SQL.
    forward_results = iter([v2, v3, None])

    async def fake_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=next(forward_results))
        return result

    db.get = AsyncMock(side_effect=fake_get)
    db.execute = AsyncMock(side_effect=fake_execute)

    with patch.object(service, "get", new=AsyncMock(return_value=v2)):
        chain = await service.list_versions(db, org_id, v2_id, scope=SYSTEM_SCOPE)

    assert [d.id for d in chain] == [v1_id, v2_id, v3_id]
