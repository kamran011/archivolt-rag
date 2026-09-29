"""
Static isolation guard for the retrieval engines (master spec section 37).

Vector search needs pgvector's HNSW index and keyword search needs a real
tsvector/GIN index — neither works under SQLite, so these can't run as
live queries without Postgres. Instead, these tests compile the actual
SELECT statements the engines build and assert `organization_id` is
present in every WHERE clause. This catches the regression class that
matters most here: someone editing vector_engine.py or keyword_engine.py
and accidentally dropping the tenant filter. It does NOT prove the filter
is enforced correctly by a live database — that still needs a real
Postgres/Supabase integration run before this goes to production.
"""

import uuid

import pytest

from app.domains.retrieval.engines.keyword_engine import KeywordRetrievalEngine
from app.domains.retrieval.engines.vector_engine import VectorRetrievalEngine


def compiled_sql_and_params(stmt) -> tuple[str, dict]:
    """Compiles without literal_binds (some of our column types — pgvector,
    REGCONFIG for tsquery — have no generic-dialect literal renderer) and
    returns the SQL text plus the bound parameter dict separately."""
    compiled = stmt.compile()
    return str(compiled), dict(compiled.params)


@pytest.mark.asyncio
async def test_vector_engine_query_always_filters_by_organization_id():
    org_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    captured = {}

    class FakeDB:
        async def execute(self, stmt):
            captured["stmt"] = stmt

            class EmptyResult:
                def all(self):
                    return []

            return EmptyResult()

    class FakeEmbeddingProvider:
        async def embed_query(self, query):
            return [0.0] * 1536

    engine = VectorRetrievalEngine()
    from unittest.mock import patch

    with patch(
        "app.domains.retrieval.engines.vector_engine.get_embedding_provider",
        return_value=FakeEmbeddingProvider(),
    ):
        await engine.search(FakeDB(), org_id, "test query", [kb_id], top_k=10)

    sql, params = compiled_sql_and_params(captured["stmt"])
    assert "organization_id" in sql
    assert org_id in params.values()


@pytest.mark.asyncio
async def test_keyword_engine_query_always_filters_by_organization_id():
    org_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    captured = {}

    class FakeDB:
        async def execute(self, stmt):
            captured["stmt"] = stmt

            class EmptyResult:
                def all(self):
                    return []

            return EmptyResult()

    engine = KeywordRetrievalEngine()
    await engine.search(FakeDB(), org_id, "test query", [kb_id], top_k=10)

    sql, params = compiled_sql_and_params(captured["stmt"])
    assert "organization_id" in sql
    assert org_id in params.values()


@pytest.mark.asyncio
async def test_vector_engine_never_matches_a_different_orgs_id_string():
    """Sanity check on the test technique itself: a random org id that was
    NOT passed to search() must not appear in the compiled query."""
    org_id = uuid.uuid4()
    other_org_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    captured = {}

    class FakeDB:
        async def execute(self, stmt):
            captured["stmt"] = stmt

            class EmptyResult:
                def all(self):
                    return []

            return EmptyResult()

    class FakeEmbeddingProvider:
        async def embed_query(self, query):
            return [0.0] * 1536

    engine = VectorRetrievalEngine()
    from unittest.mock import patch

    with patch(
        "app.domains.retrieval.engines.vector_engine.get_embedding_provider",
        return_value=FakeEmbeddingProvider(),
    ):
        await engine.search(FakeDB(), org_id, "test query", [kb_id], top_k=10)

    _, params = compiled_sql_and_params(captured["stmt"])
    assert other_org_id not in params.values()
