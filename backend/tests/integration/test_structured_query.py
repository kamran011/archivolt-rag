"""structured_query on real Postgres: correctness, safety against hostile arguments,
access control, tenancy and reprocessing."""

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.domains.retrieval.access import AccessScope
from app.domains.tools.base import ToolContext, ToolExecutor
from app.domains.tools.registry import default_registry
from app.main import app
from app.models.document_row import DocumentRow
from app.models.organization_member import OrgRole
from tests.integration.test_agent_tools import executor as make_executor  # noqa: F401
from tests.integration.test_document_access import add_member
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    onboard,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

CSV = """region,qty,price,note
EU,3,9.5,ok
EU,5,10.0,ok
US,2,7.25,late delivery
US,10,100,50%_off
APAC,,abc,none
"""
ADMIN = AccessScope(user_id=uuid.uuid4(), is_admin=True)


async def upload_file(c, h, kb, name, data: bytes, mime="text/csv", restricted=False):
    r = await c.post(
        f"/api/v1/knowledge-bases/{kb}/documents/upload",
        files={"file": (name, data, mime)},
        data={"restricted": str(restricted).lower()},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ex(db, org, kb, scope=ADMIN, role=OrgRole.admin) -> ToolExecutor:
    return ToolExecutor(
        default_registry,
        ToolContext(db=db, org_id=uuid.UUID(org), kb_ids=[uuid.UUID(kb)], scope=scope, role=role),
    )


@pytest.fixture
async def world(env):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"sq-{uuid.uuid4().hex[:6]}")
        doc = await upload_file(c, h, kb, "sales.csv", CSV.encode())
        yield {"c": c, "h": h, "kb": kb, "org": h["X-Organization-Id"], "doc": doc,
               "env": env, "orgs": orgs}


async def q(world, **args):
    maker = world["env"][0]
    async with maker() as s:
        return await ex(s, world["org"], world["kb"]).call(
            "structured_query", {"document_title": "sales", **args}
        )


def value_of(result) -> str:
    return result.content.split(" (")[0]


async def test_rows_are_stored_typed(world):
    maker = world["env"][0]
    async with maker() as s:
        rows = (
            await s.execute(
                select(DocumentRow.data).where(DocumentRow.document_id == uuid.UUID(world["doc"]))
                .order_by(DocumentRow.row_index)
            )
        ).scalars().all()
    assert rows[0] == {"region": "EU", "qty": 3, "price": 9.5, "note": "ok"}
    assert rows[1]["price"] == 10 and rows[3]["price"] == 100
    assert rows[4] == {"region": "APAC", "qty": "", "price": "abc", "note": "none"}


@pytest.mark.parametrize(
    "args,expected",
    [
        ({}, "count = 5"),
        ({"filters": [{"column": "region", "op": "eq", "value": "eu"}]}, "count = 2"),
        ({"filters": [{"column": "REGION", "op": "neq", "value": "EU"}]}, "count = 3"),
        ({"filters": [{"column": "qty", "op": "gt", "value": 4}]}, "count = 2"),
        ({"filters": [{"column": "qty", "op": "gte", "value": "5"}]}, "count = 2"),
        ({"filters": [{"column": "qty", "op": "eq", "value": "3"}]}, "count = 1"),
        ({"filters": [{"column": "qty", "op": "eq", "value": 3}]}, "count = 1"),
        ({"filters": [{"column": "note", "op": "contains", "value": "LATE"}]}, "count = 1"),
        ({"aggregate": "sum", "column": "qty"}, "sum = 20"),  # blank cell ignored, no error
        ({"aggregate": "sum", "column": "qty",
          "filters": [{"column": "region", "op": "eq", "value": "EU"}]}, "sum = 8"),
        ({"aggregate": "avg", "column": "price"}, "avg = 31.6875"),  # 'abc' ignored
        ({"aggregate": "max", "column": "price"}, "max = 100"),
        ({"aggregate": "min", "column": "qty"}, "min = 2"),
        ({"aggregate": "sum", "column": "price",
          "filters": [{"column": "region", "op": "eq", "value": "nowhere"}]}, "sum = None"),
    ],
)
async def test_queries_return_correct_answers(world, args, expected):
    r = await q(world, **args)
    assert r.ok, r.error
    assert value_of(r) == expected


async def test_result_is_a_citable_evidence_chunk_with_samples(world):
    r = await q(world, aggregate="sum", column="qty",
                filters=[{"column": "region", "op": "eq", "value": "EU"}])
    [chunk] = r.chunks
    assert chunk.document_title == "sales" and str(chunk.document_id) == world["doc"]
    assert chunk.retrieval_method == "structured"
    assert "sum(qty) where region = 'EU' = 8" in chunk.content
    assert "| EU | 3 | 9.5 | ok |" in chunk.content
    assert chunk.metadata["derived_from"] == ["structured_query"]
    # Same query -> same id, so repeated calls dedupe instead of piling up.
    again = await q(world, aggregate="sum", column="qty",
                    filters=[{"column": "region", "op": "eq", "value": "EU"}])
    assert again.chunks[0].chunk_id == chunk.chunk_id


async def test_wildcards_in_contains_are_literal(world):
    assert value_of(await q(world, filters=[{"column": "note", "op": "contains", "value": "%"}])) == "count = 1"
    assert value_of(await q(world, filters=[{"column": "note", "op": "contains", "value": "_"}])) == "count = 1"
    assert value_of(await q(world, filters=[{"column": "note", "op": "contains", "value": "%%"}])) == "count = 0"


@pytest.mark.parametrize(
    "args,fragment",
    [
        ({"aggregate": "sum"}, "needs a column"),
        ({"aggregate": "sum", "column": "nope"}, "unknown column"),
        ({"filters": [{"column": "nope", "op": "eq", "value": 1}]}, "unknown column"),
        # hostile column names are just unknown names, never SQL or JSON paths
        ({"filters": [{"column": "x'); DROP TABLE documents;--", "op": "eq", "value": 1}]},
         "unknown column"),
        ({"filters": [{"column": "qty->>'a'", "op": "eq", "value": 1}]}, "unknown column"),
        ({"filters": [{"column": "note", "op": "gt", "value": "abc"}]}, "needs a numeric value"),
        ({"filters": [{"column": "note", "op": "contains", "value": 5}]}, "needs a text value"),
    ],
)
async def test_bad_queries_fail_cleanly(world, args, fragment):
    r = await q(world, **args)
    assert not r.ok and fragment in r.error


async def test_values_are_bound_parameters_not_sql(world):
    maker = world["env"][0]
    evil = "'; DROP TABLE document_rows; --"
    r = await q(world, filters=[{"column": "note", "op": "eq", "value": evil}])
    assert r.ok and value_of(r) == "count = 0"
    async with maker() as s:
        assert (await s.execute(select(func.count()).select_from(DocumentRow))).scalar_one() >= 5


@pytest.mark.parametrize(
    "args",
    [
        {"op": "between"},  # not an allowed operator
        {"aggregate": "median", "column": "qty"},
        {"document_title": "x"},  # too short
    ],
)
async def test_grammar_is_closed(world, args):
    maker = world["env"][0]
    base = {"document_title": "sales"}
    payload = ({**base, "filters": [{"column": "qty", "op": args["op"], "value": 1}]}
               if "op" in args else {**base, **args})
    async with maker() as s:
        r = await ex(s, world["org"], world["kb"]).call("structured_query", payload)
    assert not r.ok and r.error.startswith("Invalid arguments")


async def test_too_many_filters_rejected(world):
    maker = world["env"][0]
    filters = [{"column": "qty", "op": "gt", "value": i} for i in range(6)]
    async with maker() as s:
        r = await ex(s, world["org"], world["kb"]).call(
            "structured_query", {"document_title": "sales", "filters": filters}
        )
    assert not r.ok and r.error.startswith("Invalid arguments")


async def test_only_tabular_documents_are_queryable(world):
    c, maker = world["c"], world["env"][0]
    await upload_file(c, world["h"], world["kb"], "handbook.md", b"# Handbook\n\nText only.\n",
                      "text/markdown")
    async with maker() as s:
        r = await ex(s, world["org"], world["kb"]).call(
            "structured_query", {"document_title": "handbook"}
        )
    assert r.ok and "no tabular document" in r.content and r.chunks == []


async def test_json_record_lists_are_queryable(world):
    c, maker = world["c"], world["env"][0]
    data = json.dumps([{"sku": "A1", "stock": 4}, {"sku": "B2", "stock": 9}]).encode()
    await upload_file(c, world["h"], world["kb"], "inventory.json", data, "application/json")
    async with maker() as s:
        r = await ex(s, world["org"], world["kb"]).call(
            "structured_query",
            {"document_title": "inventory", "aggregate": "sum", "column": "stock"},
        )
    assert r.ok and value_of(r) == "sum = 13"


async def test_restricted_tables_respect_access_and_tenancy(world):
    c, maker = world["c"], world["env"][0]
    await upload_file(c, world["h"], world["kb"], "payroll.csv", b"name,salary\nAnn,100\nBob,200\n",
                      restricted=True)
    member, _ = await add_member(c, world["h"])
    member_scope = AccessScope(user_id=member, is_admin=False)
    args = {"document_title": "payroll", "aggregate": "sum", "column": "salary"}
    async with maker() as s:
        member_ex = ex(s, world["org"], world["kb"], member_scope, OrgRole.member)
        r = await member_ex.call("structured_query", args)
        assert r.ok and r.chunks == [] and "no tabular document" in r.content
        assert (await ex(s, world["org"], world["kb"], None, OrgRole.member).call(
            "structured_query", args)).chunks == []  # fail closed with no scope
        admin = await ex(s, world["org"], world["kb"]).call("structured_query", args)
        assert value_of(admin) == "sum = 300"

        # Another tenant, even pointed at this knowledge base, sees nothing.
        h_b, _ = await onboard(c, world["orgs"], uuid.uuid4(), f"sqb-{uuid.uuid4().hex[:6]}")
        other = await ex(s, h_b["X-Organization-Id"], world["kb"]).call("structured_query", args)
        assert other.chunks == []


async def test_reprocessing_replaces_rows(world):
    c, maker = world["c"], world["env"][0]

    async def n():
        async with maker() as s:
            return (await s.execute(
                select(func.count()).select_from(DocumentRow)
                .where(DocumentRow.document_id == uuid.UUID(world["doc"]))
            )).scalar_one()

    assert await n() == 5
    r = await c.post(f"/api/v1/ingestion/documents/{world['doc']}/reprocess", headers=world["h"])
    assert r.status_code == 202, r.text
    assert await n() == 5

    async with maker() as s:  # rows vanish with the document
        await s.execute(text("DELETE FROM documents WHERE id = :i"), {"i": world["doc"]})
        await s.commit()
    assert await n() == 0
