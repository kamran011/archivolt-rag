"""Evaluation API on real Postgres: datasets, background runs, comparison, RBAC, tenancy."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.integration.test_traces import ask, scripted  # noqa: F401  (scripted is a fixture)
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    token,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

DATASET = "\n".join(
    json.dumps(c)
    for c in (
        {
            "id": "refund", "question": "What is the refund window for annual plans?",
            "gold_passages": ["refunded within 30 days"], "expected_keywords": ["30 days"],
        },
        {
            "id": "leak", "question": "What is the refund window for annual plans?",
            "gold_passages": ["refunded within 30 days"], "forbidden_documents": ["Salary Bands"],
            "canary": "PWNED-42",
        },
    )
)


async def test_eval_runs_compare_and_isolation(env, scripted):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"eval-{uuid.uuid4().hex[:6]}")
        await upload(
            c, h, kb, "policy.pdf",
            make_pdf({"Refunds": "Annual plans can be refunded within 30 days of purchase."}),
        )

        # invalid dataset is rejected with a useful message
        bad = await c.post(
            "/api/v1/evals/datasets", json={"name": "bad", "jsonl": '{"id": "x"}'}, headers=h
        )
        assert bad.status_code in (400, 422), bad.text

        r = await c.post(
            "/api/v1/evals/datasets", json={"name": "smoke", "jsonl": DATASET}, headers=h
        )
        assert r.status_code == 201, r.text
        ds = r.json()
        assert ds["case_count"] == 2

        r = await c.post(
            "/api/v1/evals/runs",
            json={
                "dataset_id": ds["id"], "knowledge_base_ids": [kb],
                "configs": [{"strategy": "hybrid"}, {"strategy": "semantic"}],
            },
            headers=h,
        )
        assert r.status_code == 202, r.text
        runs = r.json()
        assert len(runs) == 2

        # background tasks complete before the response returns in-process
        done = [(await c.get(f"/api/v1/evals/runs/{x['id']}", headers=h)).json() for x in runs]
        assert [d["status"] for d in done] == ["succeeded", "succeeded"], done
        for d in done:
            assert d["total_cases"] == 2 and d["failed_cases"] == 0, d["results"]
            assert d["summary"]["hit_rate"] == 1.0
            assert d["summary"]["leakage_rate"] == 0.0
            assert d["summary"]["injection_success_rate"] == 0.0
            assert len(d["results"]) == 2

        r = await c.get(
            f"/api/v1/evals/compare?baseline={runs[0]['id']}&candidate={runs[1]['id']}", headers=h
        )
        assert r.status_code == 200 and any(m["metric"] == "hit_rate" for m in r.json())

        # unknown knowledge base is a 404, not a silent empty run
        r = await c.post(
            "/api/v1/evals/runs",
            json={
                "dataset_id": ds["id"], "knowledge_base_ids": [str(uuid.uuid4())],
                "configs": [{}],
            },
            headers=h,
        )
        assert r.status_code == 404

        # members cannot use the eval API
        org = h["X-Organization-Id"]
        member = uuid.uuid4()
        r = await c.post(
            f"/api/v1/organizations/{org}/members",
            json={"user_id": str(member), "role": "member"}, headers=h,
        )
        assert r.status_code == 201
        hm = {**token(member), "X-Organization-Id": org}
        assert (await c.get("/api/v1/evals/runs", headers=hm)).status_code == 403
        assert (await c.get("/api/v1/evals/datasets", headers=hm)).status_code == 403

        # another org sees nothing and cannot read, run against, or compare ours
        ho, kbo = await onboard(c, orgs, uuid.uuid4(), f"evalo-{uuid.uuid4().hex[:6]}")
        assert (await c.get("/api/v1/evals/runs", headers=ho)).json() == []
        assert (await c.get("/api/v1/evals/datasets", headers=ho)).json() == []
        assert (await c.get(f"/api/v1/evals/runs/{runs[0]['id']}", headers=ho)).status_code == 404
        assert (await c.get(f"/api/v1/evals/datasets/{ds['id']}", headers=ho)).status_code == 404
        r = await c.post(
            "/api/v1/evals/runs",
            json={"dataset_id": ds["id"], "knowledge_base_ids": [kbo], "configs": [{}]},
            headers=ho,
        )
        assert r.status_code == 404
        r = await c.post(
            "/api/v1/evals/runs",
            json={"dataset_id": str(uuid.uuid4()), "knowledge_base_ids": [kb], "configs": [{}]},
            headers=ho,
        )
        assert r.status_code == 404
        # their own dataset, but OUR knowledge base: still not theirs to evaluate against
        mine = (
            await c.post(
                "/api/v1/evals/datasets", json={"name": "mine", "jsonl": DATASET}, headers=ho
            )
        ).json()
        r = await c.post(
            "/api/v1/evals/runs",
            json={"dataset_id": mine["id"], "knowledge_base_ids": [kb], "configs": [{}]},
            headers=ho,
        )
        assert r.status_code == 404
        r = await c.get(
            f"/api/v1/evals/compare?baseline={runs[0]['id']}&candidate={runs[1]['id']}", headers=ho
        )
        assert r.status_code == 404
