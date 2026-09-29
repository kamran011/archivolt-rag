import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.domains.ingestion.schemas import ChunkData
from app.domains.retrieval.engines.tree_engine import TreeRetrievalEngine
from app.domains.retrieval.expansion import expand_with_neighbors
from app.domains.retrieval.query_router import query_router
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.retrieval.tree import (
    build_tree,
    iter_nodes,
    render_outline,
    subtree_chunk_indices,
    tree_from_json,
    tree_to_json,
)


def cd(idx: int, hierarchy: list[str]) -> ChunkData:
    return ChunkData(
        content=f"c{idx}", chunk_index=idx, token_count=5,
        metadata={"heading_hierarchy": hierarchy},
    )


# ── tree ─────────────────────────────────────────────────────────────────────

def test_build_tree_nests_by_hierarchy():
    tree = build_tree([
        cd(0, ["Intro"]),
        cd(1, ["Policy", "Refunds"]),
        cd(2, ["Policy", "Refunds"]),
        cd(3, ["Policy", "Shipping"]),
    ])
    assert [n.title for n in tree] == ["Intro", "Policy"]
    policy = tree[1]
    assert [c.title for c in policy.children] == ["Refunds", "Shipping"]
    assert policy.children[0].chunk_indices == [1, 2]
    assert sorted(subtree_chunk_indices(policy)) == [1, 2, 3]


def test_build_tree_handles_chunks_without_headings():
    tree = build_tree([cd(0, []), cd(1, [])])
    assert len(tree) == 1 and tree[0].chunk_indices == [0, 1]


def test_tree_json_roundtrip_and_outline():
    tree = build_tree([cd(0, ["A", "B"])])
    restored = tree_from_json(tree_to_json(tree))
    assert [n.title for n in iter_nodes(restored)] == ["A", "B"]
    outline = render_outline("Doc", restored, "d1")
    assert "[d1:n1] A" in outline and "[d1:n2] B" in outline


# ── router ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query,expected",
    [
        ("Summarize this document", "tree"),
        ("Give me an overview of the refund policy", "tree"),
        ('What does "force majeure" say?', "keyword"),
        ("What is in section 4.2?", "keyword"),
        ("Find contract ACME-2024-17", "keyword"),
        ("Why does the system retry failed uploads twice", "semantic"),
        ("What is the refund window?", "hybrid"),
    ],
)
def test_router(query, expected):
    assert query_router.route(query).strategy == expected


def test_router_falls_back_when_no_tree():
    assert query_router.route("Summarize this", tree_available=False).strategy == "hybrid"


# ── tree engine ──────────────────────────────────────────────────────────────

def make_doc(tree_json):
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.title = "Handbook"
    doc.parsing_metadata = {"tree": tree_json}
    return doc


@pytest.mark.asyncio
async def test_tree_engine_drops_fabricated_node_refs():
    tree = build_tree([cd(0, ["A"]), cd(1, ["B"])])
    doc = make_doc(tree_to_json(tree))
    engine = TreeRetrievalEngine()

    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value=MagicMock(content='{"nodes": ["d1:n2", "d9:n1", "d1:n99", 7]}')
    )
    with patch("app.domains.retrieval.engines.tree_engine.get_llm_provider", return_value=llm):
        picked = await engine._select_nodes("q", {"d1": (doc, tree)})

    assert [(k, n.title) for k, n in picked] == [("d1", "B")]


@pytest.mark.asyncio
async def test_tree_engine_navigation_failure_returns_empty():
    tree = build_tree([cd(0, ["A"])])
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("app.domains.retrieval.engines.tree_engine.get_llm_provider", return_value=llm):
        picked = await TreeRetrievalEngine()._select_nodes("q", {"d1": (make_doc([]), tree)})
    assert picked == []


@pytest.mark.asyncio
async def test_tree_engine_no_trees_returns_empty():
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [make_doc(None)]
    db.execute = AsyncMock(return_value=result)
    out = await TreeRetrievalEngine().search(db, uuid.uuid4(), "q", [uuid.uuid4()], 5)
    assert out == []


@pytest.mark.asyncio
async def test_tree_engine_queries_are_org_scoped():
    org_id = uuid.uuid4()
    tree = build_tree([cd(0, ["A"])])
    doc = make_doc(tree_to_json(tree))

    captured = []
    doc_result = MagicMock()
    doc_result.scalars.return_value.all.return_value = [doc]
    chunk_result = MagicMock()
    chunk_result.all.return_value = []

    async def execute(stmt):
        captured.append(stmt)
        return doc_result if len(captured) == 1 else chunk_result

    db = MagicMock()
    db.execute = execute
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=MagicMock(content='{"nodes": ["d1:n1"]}'))

    with patch("app.domains.retrieval.engines.tree_engine.get_llm_provider", return_value=llm):
        await TreeRetrievalEngine().search(db, org_id, "q", [uuid.uuid4()], 5)

    assert len(captured) == 2
    for stmt in captured:
        compiled = stmt.compile(dialect=postgresql.dialect())
        assert org_id in compiled.params.values()


# ── neighbor expansion ───────────────────────────────────────────────────────

def rc(doc_id, idx, score=0.8):
    return RetrievedChunk(
        chunk_id=uuid.uuid4(), document_id=doc_id, document_title="D", content="x",
        score=score, metadata={"chunk_index": idx}, retrieval_method="hybrid",
    )


@pytest.mark.asyncio
async def test_expansion_is_org_scoped_and_skips_missing_index():
    org_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    captured = []

    async def execute(stmt):
        captured.append(stmt)
        r = MagicMock()
        r.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute

    seed = rc(doc_id, 5)
    no_idx = rc(doc_id, 0)
    no_idx.metadata.pop("chunk_index")
    out = await expand_with_neighbors(db, org_id, [seed, no_idx])
    assert out == [seed, no_idx]
    compiled = captured[0].compile(dialect=postgresql.dialect())
    assert org_id in compiled.params.values()


@pytest.mark.asyncio
async def test_expansion_no_seeds_makes_no_query():
    db = MagicMock()
    db.execute = AsyncMock()
    chunk = rc(uuid.uuid4(), 0)
    chunk.metadata.pop("chunk_index")
    assert await expand_with_neighbors(db, uuid.uuid4(), [chunk]) == [chunk]
    db.execute.assert_not_called()
