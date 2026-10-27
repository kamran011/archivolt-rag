import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domains.ingestion.dedup import (
    content_hash,
    find_near_duplicates,
    load_reusable_embeddings,
    overlap_ratio,
)
from app.models.document import Document


def test_content_hash_ignores_whitespace_but_not_content():
    assert content_hash("a  b\n c") == content_hash(" a b c ")
    assert content_hash("a b c") != content_hash("a b d")


def test_overlap_ratio():
    assert overlap_ratio(["a", "b", "c", "d"], {"a", "b", "z"}) == 0.5
    assert overlap_ratio([], {"a"}) == 0.0


@pytest.mark.asyncio
async def test_load_reusable_embeddings_skips_query_without_previous_version():
    db = AsyncMock()
    assert await load_reusable_embeddings(db, None, ["a"]) == {}
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_load_reusable_embeddings_maps_hash_to_vector():
    result = MagicMock()
    result.all.return_value = [("h1", [0.1]), ("h2", [0.2])]
    db = AsyncMock()
    db.execute.return_value = result
    out = await load_reusable_embeddings(db, uuid.uuid4(), ["h1", "h2", "h3"])
    assert out == {"h1": [0.1], "h2": [0.2]}


@pytest.mark.asyncio
async def test_find_near_duplicates_applies_threshold():
    dup, partial = uuid.uuid4(), uuid.uuid4()
    result = MagicMock()
    result.all.return_value = [
        (dup, "a", "copy.pdf"),
        (dup, "b", "copy.pdf"),
        (dup, "c", "copy.pdf"),
        (dup, "d", "copy.pdf"),
        (partial, "a", "other.pdf"),
    ]
    db = AsyncMock()
    db.execute.return_value = result
    doc = Document(id=uuid.uuid4(), organization_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
    matches = await find_near_duplicates(db, doc, ["a", "b", "c", "d"], threshold=0.9)
    assert matches == [{"document_id": str(dup), "file_name": "copy.pdf", "overlap": 1.0}]
