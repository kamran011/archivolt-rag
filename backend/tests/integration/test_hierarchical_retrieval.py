"""Hierarchical summary retrieval and parent expansion on real Postgres.

Summaries are generated with a scripted LLM and embedded with the test's deterministic
embedder; everything else (SQL, RLS-relevant filters, ingestion, endpoints) is real."""

import json
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.expansion import expand_with_parents
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.main import app
from app.models import Chunk, Document
from app.models.summary import DocumentSummary
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    FakeEmbedder,
    env,
    onboard,
    token,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

HANDBOOK = """# Handbook

## Refunds

Refund policy: annual plans can be refunded within thirty days of purchase.
Contact billing support to request a refund.

### Annual plans

Annual plan refunds are prorated after thirty days.

### Monthly plans

Monthly plans cannot be refunded once the billing cycle starts.

## Shipping

Shipping policy: orders leave the warehouse within five business days.
Carriers deliver packages to the delivery address.
"""


class SummaryLLM:
    """Scripted summarizer: one sentence per section, an overview for the document."""

    async def generate(self, messages, temperature=0.1, max_tokens=2048):
        from app.providers.llm.base import LLMResponse

        prompt = messages[-1]["content"]
        if "Document title:" in prompt:
            body = "Handbook overview covering refunds and shipping policies."
        else:
            title = re.search(r"Section: (.*)", prompt).group(1).strip()
            body = f"Explains {title.lower()} policy details."
        return LLMResponse(
            content=body, prompt_tokens=5, completion_tokens=5, model="f", finish_reason="stop"
        )


@pytest.fixture
def hier(monkeypatch, env):  # noqa: F811
    monkeypatch.setattr(settings, "ENABLE_SECTION_SUMMARIES", True)
    llm = SummaryLLM()
    monkeypatch.setattr("app.domains.ingestion.summarizer.get_llm_provider", lambda m: llm)
    monkeypatch.setattr("app.domains.ingestion.service.get_llm_provider", lambda m: llm)
    monkeypatch.setattr(
        "app.domains.retrieval.engines.summary_engine.get_embedding_provider",
        lambda m: FakeEmbedder(),
    )
    return llm


async def upload_md(c, h, kb, name, text, restricted=False):
    r = await c.post(
        f"/api/v1/knowledge-bases/{kb}/documents/upload",
        files={"file": (name, text.encode(), "text/markdown")},
        data={"restricted": str(restricted).lower()},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def add_member(c, h_owner):
    user = uuid.uuid4()
    org = h_owner["X-Organization-Id"]
    r = await c.post(
        f"/api/v1/organizations/{org}/members",
        json={"user_id": str(user), "role": "member"},
        headers=h_owner,
    )
    assert r.status_code == 201, r.text
    return user, {**token(user), "X-Organization-Id": org}


async def search(c, h, kb, query, strategy="summary", top_k=10):
    r = await c.post(
        "/api/v1/retrieval/search",
        json={"query": query, "knowledge_base_ids": [kb], "strategy": strategy, "top_k": top_k},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_summaries_are_indexed_and_navigation_ends_in_raw_chunks(env, hier):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"hier-{uuid.uuid4().hex[:6]}")
        doc = await upload_md(c, h, kb, "handbook.md", HANDBOOK)

        r = await c.get(f"/api/v1/knowledge-bases/{kb}/documents/{doc}/summaries", headers=h)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert [i["level"] for i in items].count("document") == 1
        titles = {i["title"] for i in items if i["level"] == "section"}
        assert {"Refunds", "Shipping"} <= titles

        result = await search(c, h, kb, "shipping policy carriers delivery")
        assert result["strategy"] == "summary"  # did not degrade to hybrid
        chunks = result["chunks"]
        assert chunks and chunks[0]["retrieval_method"] == "summary"
        # Evidence is raw source text, never the model-written summary.
        text = json.dumps(chunks)
        assert "Carriers deliver packages" in text
        assert "Explains" not in text and "Handbook overview" not in text
        # The best chunk belongs to the shipping section, not refunds.
        assert "Shipping" in " ".join(chunks[0]["metadata"]["heading_hierarchy"])

        refunds = await search(c, h, kb, "refund annual plans thirty days")
        assert "Refunds" in " ".join(refunds["chunks"][0]["metadata"]["heading_hierarchy"])

        async with maker() as s:
            n = (await s.execute(select(func.count()).select_from(DocumentSummary))).scalar_one()
            assert n >= 3


async def test_summary_strategy_degrades_to_hybrid_without_summaries(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "ENABLE_SECTION_SUMMARIES", False)
    monkeypatch.setattr(
        "app.domains.retrieval.engines.summary_engine.get_embedding_provider",
        lambda m: FakeEmbedder(),
    )
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"nosum-{uuid.uuid4().hex[:6]}")
        await upload_md(c, h, kb, "handbook.md", HANDBOOK)
        result = await search(c, h, kb, "shipping carriers delivery")
        assert result["strategy"] == "hybrid" and result["chunks"]


async def test_summaries_respect_tenancy_and_document_access(env, hier):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h_a, kb_a = await onboard(c, orgs, uuid.uuid4(), f"sa-{uuid.uuid4().hex[:6]}")
        secret = HANDBOOK.replace("Refunds", "Acquisitions").replace(
            "Refund policy", "Merger codename Falcon"
        )
        open_doc = await upload_md(c, h_a, kb_a, "open.md", HANDBOOK)
        secret_doc = await upload_md(c, h_a, kb_a, "secret.md", secret, restricted=True)
        member, h_member = await add_member(c, h_a)

        # The member cannot find the restricted document through summaries or read them.
        result = await search(c, h_member, kb_a, "acquisitions merger codename")
        assert "Falcon" not in json.dumps(result) and "Acquisitions" not in json.dumps(result)
        base = f"/api/v1/knowledge-bases/{kb_a}/documents"
        assert (await c.get(f"{base}/{secret_doc}/summaries", headers=h_member)).status_code == 404
        assert (await c.get(f"{base}/{open_doc}/summaries", headers=h_member)).status_code == 200
        # The owner can.
        owner_result = await search(c, h_a, kb_a, "acquisitions merger codename")
        assert "Falcon" in json.dumps(owner_result)

        # Another tenant cannot reach any of it, even with the right knowledge-base id.
        h_b, kb_b = await onboard(c, orgs, uuid.uuid4(), f"sb-{uuid.uuid4().hex[:6]}")
        await upload_md(c, h_b, kb_b, "b.md", "# B\n\n## Other\n\nUnrelated content about gardens.\n")
        cross = await search(c, h_b, kb_a, "acquisitions merger codename shipping refunds")
        assert cross["chunks"] == []
        own = await search(c, h_b, kb_b, "gardens")
        assert "Falcon" not in json.dumps(own) and "Handbook" not in json.dumps(own)


async def test_reprocessing_replaces_summaries_without_duplicates(env, hier):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"rep-{uuid.uuid4().hex[:6]}")
        doc = await upload_md(c, h, kb, "handbook.md", HANDBOOK)

        async def count():
            async with maker() as s:
                return (
                    await s.execute(
                        select(func.count())
                        .select_from(DocumentSummary)
                        .where(DocumentSummary.document_id == uuid.UUID(doc))
                    )
                ).scalar_one()

        before = await count()
        assert before >= 3
        r = await c.post(f"/api/v1/ingestion/documents/{doc}/reprocess", headers=h)
        assert r.status_code == 202, r.text
        assert await count() == before


async def test_parent_expansion_adds_section_context_and_respects_access(env, hier):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"par-{uuid.uuid4().hex[:6]}")
        open_doc = await upload_md(c, h, kb, "handbook.md", HANDBOOK)
        secret_doc = await upload_md(c, h, kb, "secret.md", HANDBOOK, restricted=True)
        member, _ = await add_member(c, h)
    org = uuid.UUID(h["X-Organization-Id"])

    async def seed_for(session, doc_id, needle):
        row = (
            await session.execute(
                select(Chunk, Document)
                .join(Document, Document.id == Chunk.document_id)
                .where(Document.id == uuid.UUID(doc_id), Chunk.content.contains(needle))
            )
        ).first()
        return row_to_retrieved_chunk(row[0], row[1], 0.9, "semantic")

    async with maker() as s:
        seed = await seed_for(s, open_doc, "Annual plan refunds are prorated")
        assert seed.metadata["heading_hierarchy"][-1] == "Annual plans"

        admin = AccessScope(user_id=uuid.uuid4(), is_admin=True)
        expanded = await expand_with_parents(s, org, [seed], scope=admin)
        added = [c for c in expanded if c.chunk_id != seed.chunk_id]
        assert added and all(c.retrieval_method == "parent" for c in added)
        joined = " ".join(c.content for c in added)
        # The enclosing "Refunds" section (and its sibling subsection) comes along...
        assert "Monthly plans cannot be refunded" in joined
        # ...but not an unrelated section, and only from the same document.
        assert "Carriers deliver" not in joined
        assert {c.document_id for c in added} == {seed.document_id}
        assert all(c.score < seed.score for c in added)

        # A seed from a restricted document gains nothing for an unauthorized member,
        # nor when no scope is given (fail closed).
        secret_seed = await seed_for(s, secret_doc, "Annual plan refunds are prorated")
        member_scope = AccessScope(user_id=member, is_admin=False)
        assert len(await expand_with_parents(s, org, [secret_seed], scope=member_scope)) == 1
        assert len(await expand_with_parents(s, org, [secret_seed])) == 1
        # ...while an admin does get the parent context.
        assert len(await expand_with_parents(s, org, [secret_seed], scope=admin)) > 1
