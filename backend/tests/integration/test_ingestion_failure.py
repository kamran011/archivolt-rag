"""Ingestion failure handling against real Postgres (see test_upload_to_search.py)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.domains.ingestion.background import recover_stuck_ingestions
from app.main import app
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


async def get_doc(client, h, kb, doc):
    r = await client.get(f"/api/v1/knowledge-bases/{kb}/documents/{doc}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


async def test_failed_ingestion_status_is_persisted(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        h, kb = await onboard(client, orgs, uuid.uuid4(), f"fail-{uuid.uuid4().hex[:6]}")
        doc_id = await upload(client, h, kb, "broken.pdf", b"this is not a pdf")

        doc = await get_doc(client, h, kb, doc_id)
        # Regression: this used to stay in 'parsing' because the rollback erased 'failed'.
        assert doc["status"] == "failed", doc
        assert doc["error_message"]


async def test_recover_stuck_ingestions_only_touches_old_in_flight_docs(env):  # noqa: F811
    maker, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        h, kb = await onboard(client, orgs, uuid.uuid4(), f"stuck-{uuid.uuid4().hex[:6]}")
        old = await upload(client, h, kb, "old.pdf", make_pdf({"A": "old doc text"}))
        fresh = await upload(client, h, kb, "fresh.pdf", make_pdf({"B": "fresh doc text"}))
        done = await upload(client, h, kb, "done.pdf", make_pdf({"C": "done doc text"}))

        async with maker() as s:
            await s.execute(
                text(
                    "UPDATE documents SET status='parsing', "
                    "updated_at = now() - interval '2 hours' WHERE id = :i"
                ),
                {"i": old},
            )
            await s.execute(
                text("UPDATE documents SET status='parsing' WHERE id = :i"), {"i": fresh}
            )
            await s.commit()

        assert await recover_stuck_ingestions(older_than_minutes=30) >= 1

        assert (await get_doc(client, h, kb, old))["status"] == "failed"
        assert (await get_doc(client, h, kb, fresh))["status"] == "parsing"
        assert (await get_doc(client, h, kb, done))["status"] == "ready"
