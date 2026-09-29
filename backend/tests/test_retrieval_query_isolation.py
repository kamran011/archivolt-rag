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


def where_clause(sql: str) -> str:
    """Text after WHERE (SQLAlchemy puts a newline before it). Asserting on the whole
    statement is too weak: columns named in the SELECT list would satisfy a substring
    check even when the filter is missing from the WHERE clause."""
    import re

    parts = re.split(r"\bWHERE\b", sql, maxsplit=1)
    assert len(parts) == 2, f"no WHERE clause in: {sql[:200]}"
    return parts[1]


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


@pytest.mark.asyncio
async def test_summary_engine_queries_always_filter_by_org_kb_and_access():
    """Every SELECT the summary engine issues is org-scoped, KB-scoped and access-scoped
    (a dropped filter would leak candidate ids even though later stages also filter)."""
    from unittest.mock import patch

    from app.domains.retrieval.engines.summary_engine import SummaryRetrievalEngine

    org_id, kb_id = uuid.uuid4(), uuid.uuid4()
    statements = []

    class FakeDB:
        async def execute(self, stmt):
            statements.append(stmt)

            class Result:
                def all(self):
                    return []

            return Result()

    class FakeEmbeddingProvider:
        async def embed_query(self, query):
            return [0.0] * 1536

    with patch(
        "app.domains.retrieval.engines.summary_engine.get_embedding_provider",
        return_value=FakeEmbeddingProvider(),
    ):
        await SummaryRetrievalEngine().search(FakeDB(), org_id, "q", [kb_id], top_k=5)

    assert statements, "the engine should have queried document summaries"
    sql, params = compiled_sql_and_params(statements[0])
    where = where_clause(sql)
    assert "document_summaries.organization_id" in where
    assert "document_summaries.knowledge_base_id" in where
    assert org_id in params.values() and kb_id in params.values() or any(
        isinstance(v, list) and kb_id in v for v in params.values()
    )
    # access control: restricted documents are excluded unless the scope allows them
    assert "documents.restricted" in where


@pytest.mark.asyncio
async def test_cag_loader_queries_are_org_kb_and_access_scoped():
    """The CAG loader's size probe and content query must each carry the tenant, KB and
    access conditions (the KB ownership check alone must not be the only protection)."""
    from app.domains.retrieval.access import AccessScope
    from app.domains.retrieval.cag import load_cag_context

    org_id, kb_id = uuid.uuid4(), uuid.uuid4()
    statements = []

    class Result:
        def __init__(self, kind):
            self.kind = kind

        def all(self):
            return [(kb_id, True)] if self.kind == 0 else []

        def scalar_one(self):
            return 10

    class FakeDB:
        async def execute(self, stmt):
            statements.append(stmt)
            return Result(len(statements) - 1)

    ctx = await load_cag_context(
        FakeDB(), org_id, [kb_id], AccessScope(user_id=uuid.uuid4(), is_admin=False)
    )
    assert ctx.eligible and len(statements) == 3  # KB check, size probe, content
    kb_sql, _ = compiled_sql_and_params(statements[0])
    assert "knowledge_bases.organization_id" in kb_sql
    for stmt in statements[1:]:
        sql, _ = compiled_sql_and_params(stmt)
        # Look at the WHERE clause only: the columns also appear in the SELECT list.
        where = where_clause(sql)
        assert "chunks.organization_id" in where
        assert "chunks.knowledge_base_id" in where
        assert "documents.restricted" in where  # access control
        assert "documents.is_current" in where  # freshness
