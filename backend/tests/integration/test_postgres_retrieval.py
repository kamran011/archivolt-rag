"""Retrieval against a real Postgres with pgvector.

Skipped unless TEST_DATABASE_URL points at a database that already has the
Supabase migrations applied, e.g.:

    TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres

Rows are created with fresh UUIDs and deleted afterwards, so it is safe to run
against a local dev database.
"""

import os
import uuid

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domains.retrieval.engines.hybrid_engine import HybridRetrievalEngine
from app.domains.retrieval.engines.keyword_engine import KeywordRetrievalEngine
from app.domains.retrieval.engines.vector_engine import VectorRetrievalEngine
from app.models import Chunk, Document, KnowledgeBase, Organization
from app.models.document import DocumentStatus, FileType

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

DIM = 1536


def vec(axis: int) -> list[float]:
    v = [0.0] * DIM
    v[axis] = 1.0
    return v


class FakeEmbedder:
    """Maps query text to a fixed axis so vector results are deterministic."""

    async def embed_query(self, text: str) -> list[float]:
        return vec(0 if "refund" in text else 1)


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setattr(
        "app.domains.retrieval.engines.vector_engine.get_embedding_provider",
        lambda model: FakeEmbedder(),
    )
    engine = create_async_engine(DB_URL, connect_args={"prepared_statement_cache_size": 0})
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def make_tenant(db, label: str, content: str, axis: int):
    org = Organization(name=label, slug=f"{label}-{uuid.uuid4().hex[:8]}", settings={})
    db.add(org)
    await db.flush()
    kb = KnowledgeBase(organization_id=org.id, name="kb")
    db.add(kb)
    await db.flush()
    doc = Document(
        organization_id=org.id,
        knowledge_base_id=kb.id,
        title=label,
        file_name=f"{label}.txt",
        file_type=FileType.txt,
        file_size=1,
        storage_path=f"{org.id}/{label}.txt",
        status=DocumentStatus.ready,
    )
    db.add(doc)
    await db.flush()
    db.add(
        Chunk(
            organization_id=org.id,
            document_id=doc.id,
            knowledge_base_id=kb.id,
            content=content,
            chunk_index=0,
            token_count=5,
            metadata_={},
            embedding=vec(axis),
        )
    )
    await db.commit()
    return org, kb


@pytest.fixture
async def tenants(db):
    a = await make_tenant(db, "acme", "Refund policy for annual plans is 30 days.", 0)
    b = await make_tenant(db, "globex", "Refund secrets: globex private pricing memo.", 0)
    yield a, b
    await db.execute(delete(Organization).where(Organization.id.in_([a[0].id, b[0].id])))
    await db.commit()


async def test_fts_trigger_populates_vector(db, tenants):
    (org_a, _), _ = tenants
    row = await db.execute(
        text("SELECT fts_vector IS NOT NULL FROM chunks WHERE organization_id = :o"),
        {"o": org_a.id},
    )
    assert row.scalar_one() is True


@pytest.mark.parametrize(
    "engine", [VectorRetrievalEngine, KeywordRetrievalEngine, HybridRetrievalEngine]
)
async def test_engine_returns_only_own_tenant(db, tenants, engine):
    (org_a, kb_a), (org_b, _) = tenants
    results = await engine().search(db, org_a.id, "refund policy", [kb_a.id], top_k=5)
    assert results, "expected a hit for the tenant's own document"
    assert all("globex" not in r.content for r in results)


async def test_cross_tenant_kb_id_returns_nothing(db, tenants):
    """Tenant A supplying tenant B's KB id must not read B's chunks."""
    (org_a, _), (_, kb_b) = tenants
    for engine in (VectorRetrievalEngine, KeywordRetrievalEngine, HybridRetrievalEngine):
        results = await engine().search(db, org_a.id, "refund", [kb_b.id], top_k=5)
        assert results == []
