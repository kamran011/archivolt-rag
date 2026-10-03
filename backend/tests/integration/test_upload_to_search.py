"""Upload -> ingest -> search through the real FastAPI app and real Postgres.

Real: routing, JWT auth, RBAC, ORM, migration schema, PDF parsing, chunking,
pgvector + FTS + RRF. Faked: object storage (in-memory) and embeddings
(deterministic bag-of-words hashing), since those need Supabase Storage / OpenAI.

Skipped unless TEST_DATABASE_URL is set (see test_postgres_retrieval.py).
"""

import hashlib
import math
import os
import re
import uuid

import fitz
import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.core.database import get_db
from app.main import app
from app.models import Organization

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

DIM = 1536


def embed(text: str) -> list[float]:
    v = [0.0] * DIM
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class FakeEmbedder:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [embed(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return embed(text)


def make_pdf(sections: dict[str, str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for heading, body in sections.items():
        page.insert_text((72, y), heading, fontsize=20)
        y += 30
        for line in body.split("\n"):
            page.insert_text((72, y), line, fontsize=11)
            y += 16
        y += 20
    return doc.tobytes()


def token(user_id: uuid.UUID) -> dict[str, str]:
    t = jwt.encode(
        {"sub": str(user_id), "email": "e2e@example.com", "aud": "authenticated"},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
async def env(monkeypatch):
    engine = create_async_engine(DB_URL, connect_args={"prepared_statement_cache_size": 0})
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.domains.ingestion.background.AsyncSessionLocal", maker)
    monkeypatch.setattr("app.domains.jobs.sessions.AsyncSessionLocal", maker)

    store: dict[str, bytes] = {}

    async def upload_file(storage_path, content, content_type="application/octet-stream"):
        store[storage_path] = content

    async def download_file(storage_path):
        return store[storage_path]

    from app.domains.documents.storage import storage_service

    monkeypatch.setattr(storage_service, "upload_file", upload_file)
    monkeypatch.setattr(storage_service, "download_file", download_file)
    for target in (
        "app.domains.ingestion.service.get_embedding_provider",
        "app.domains.retrieval.engines.vector_engine.get_embedding_provider",
    ):
        monkeypatch.setattr(target, lambda model: FakeEmbedder())

    created_orgs: list[uuid.UUID] = []
    yield maker, created_orgs
    async with maker() as s:
        if created_orgs:
            await s.execute(delete(Organization).where(Organization.id.in_(created_orgs)))
            await s.commit()
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def onboard(client, created_orgs, user_id, slug):
    h = token(user_id)
    r = await client.post("/api/v1/organizations/", json={"name": slug, "slug": slug}, headers=h)
    assert r.status_code == 201, r.text
    org_id = r.json()["id"]
    created_orgs.append(uuid.UUID(org_id))
    h = {**h, "X-Organization-Id": org_id}
    r = await client.post("/api/v1/knowledge-bases/", json={"name": "Policies"}, headers=h)
    assert r.status_code == 201, r.text
    return h, r.json()["id"]


async def upload(client, h, kb_id, name, pdf):
    r = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/upload",
        files={"file": (name, pdf, "application/pdf")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_upload_ingest_search_and_tenant_isolation(env):
    _, created_orgs = env
    pdf_a = make_pdf(
        {
            "Refund Policy": "Annual plans may be refunded within 30 days of purchase.\n"
            "After 30 days no refund is issued for annual plans.",
            "Shipping": "Orders ship within 5 business days.",
        }
    )
    pdf_b = make_pdf({"Globex Memo": "Globex private pricing: secret enterprise discount 40 percent."})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        h_a, kb_a = await onboard(client, created_orgs, uuid.uuid4(), f"acme-{uuid.uuid4().hex[:6]}")
        h_b, kb_b = await onboard(client, created_orgs, uuid.uuid4(), f"globex-{uuid.uuid4().hex[:6]}")

        doc_a = await upload(client, h_a, kb_a, "policy.pdf", pdf_a)
        await upload(client, h_b, kb_b, "memo.pdf", pdf_b)

        # Background ingestion has run by now; the document should be ready.
        r = await client.get(f"/api/v1/knowledge-bases/{kb_a}/documents/{doc_a}", headers=h_a)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ready", r.json()
        assert r.json()["chunk_count"] >= 1

        for strategy in ("semantic", "keyword", "hybrid"):
            r = await client.post(
                "/api/v1/retrieval/search",
                json={
                    "query": "annual plan refund",
                    "knowledge_base_ids": [kb_a],
                    "strategy": strategy,
                },
                headers=h_a,
            )
            assert r.status_code == 200, (strategy, r.text)
            chunks = r.json()["chunks"]
            assert chunks, f"{strategy}: no results"
            assert any("refund" in c["content"].lower() for c in chunks), strategy

        # Tenant A asking about B's KB / B's content must get nothing of B's.
        r = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "globex secret discount", "knowledge_base_ids": [kb_b]},
            headers=h_a,
        )
        assert r.status_code == 200, r.text
        assert r.json()["chunks"] == []

        r = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "globex secret discount", "knowledge_base_ids": [kb_a]},
            headers=h_a,
        )
        assert all("globex" not in c["content"].lower() for c in r.json()["chunks"])

        # Client-supplied org header for an org the user does not belong to is rejected.
        h_bad = {**h_a, "X-Organization-Id": h_b["X-Organization-Id"]}
        r = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "secret", "knowledge_base_ids": [kb_b]},
            headers=h_bad,
        )
        assert r.status_code in (401, 403, 404), r.text
