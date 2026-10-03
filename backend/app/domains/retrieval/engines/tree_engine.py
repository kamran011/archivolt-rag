import json
import uuid

import structlog
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.retrieval.access import AccessScope, visible_document_clause
from app.domains.retrieval.engines.base import RetrievalEngine
from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk
from app.domains.retrieval.tree import (
    TreeNode,
    iter_nodes,
    render_outline,
    subtree_chunk_indices,
    tree_from_json,
)
from app.models.chunk import Chunk
from app.models.document import Document
from app.providers.llm.registry import get_llm_provider

logger = structlog.get_logger()

MAX_OUTLINE_DOCS = 20
MAX_SELECTED_NODES = 6
TREE_BASE_SCORE = 0.5  # navigation has no similarity score; the reranker rescores downstream

NAVIGATION_PROMPT = """You are navigating document outlines to find the sections that answer a \
question. Each line is a section reference in brackets followed by its title (and sometimes a \
summary). Choose up to {max_nodes} sections most likely to contain the answer.

Question: {query}

Outlines:
{outlines}

Respond with ONLY a JSON object: {{"nodes": ["d1:n3", "d2:n1"]}}. Use only references that \
appear above. No other text."""


class TreeRetrievalEngine(RetrievalEngine):
    """Reasoning-based retrieval: an LLM picks sections from document outlines,
    then the real source chunks of those sections are loaded. Returns [] when
    there is nothing to navigate, so callers can fall back to hybrid search."""

    async def search(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        query: str,
        kb_ids: list[uuid.UUID],
        top_k: int,
        filters: RetrievalFilters | None = None,
        embedding_model: str = "text-embedding-3-small",
        scope: AccessScope | None = None,
    ) -> list[RetrievedChunk]:
        trees = await load_document_trees(db, org_id, kb_ids, filters, scope)
        if not trees:
            return []

        selected = await self._select_nodes(query, trees)
        if not selected:
            return []

        return await fetch_node_chunks(
            db, org_id, kb_ids, filters, trees, selected, top_k, "tree", scope
        )

    async def _select_nodes(
        self, query: str, trees: dict[str, tuple[Document, list[TreeNode]]]
    ) -> list[tuple[str, TreeNode]]:
        outlines = "\n\n".join(
            render_outline(doc.title, nodes, key) for key, (doc, nodes) in trees.items()
        )
        prompt = NAVIGATION_PROMPT.format(
            max_nodes=MAX_SELECTED_NODES, query=query, outlines=outlines
        )

        try:
            llm = get_llm_provider(settings.RERANKER_MODEL)
            response = await llm.generate(
                [{"role": "user", "content": prompt}], temperature=0.0, max_tokens=256
            )
            refs = json.loads(_strip_fences(response.content)).get("nodes", [])
        except Exception as e:
            logger.warning("tree_navigation_failed", error=str(e))
            return []

        lookup = {
            f"{key}:{node.node_id}": (key, node)
            for key, (_, nodes) in trees.items()
            for node in iter_nodes(nodes)
        }
        picked: list[tuple[str, TreeNode]] = []
        for ref in refs:
            # Refs the model invented (not in any outline) are dropped, same
            # hallucination guard as citations and conflicts.
            if isinstance(ref, str) and ref in lookup and lookup[ref] not in picked:
                picked.append(lookup[ref])
            if len(picked) >= MAX_SELECTED_NODES:
                break
        return picked


async def load_document_trees(
    db: AsyncSession,
    org_id: uuid.UUID,
    kb_ids: list[uuid.UUID],
    filters: RetrievalFilters | None,
    scope: AccessScope | None = None,
) -> dict[str, tuple[Document, list[TreeNode]]]:
    """Org-scoped load of document outlines, keyed by short refs ('d1', 'd2')
    so an LLM never handles real document ids."""
    stmt = (
        select(Document)
        .where(Document.organization_id == org_id, Document.knowledge_base_id.in_(kb_ids))
        # Outlines are shown to an LLM: restricted documents' headings must never reach it.
        .where(visible_document_clause(scope))
        .limit(MAX_OUTLINE_DOCS * 3)
    )
    if not (filters and filters.include_superseded):
        stmt = stmt.where(Document.is_current.is_(True))
    if filters and filters.document_ids:
        stmt = stmt.where(Document.id.in_(filters.document_ids))

    trees: dict[str, tuple[Document, list[TreeNode]]] = {}
    for doc in (await db.execute(stmt)).scalars().all():
        nodes = tree_from_json((doc.parsing_metadata or {}).get("tree"))
        if nodes:
            trees[f"d{len(trees) + 1}"] = (doc, nodes)
        if len(trees) >= MAX_OUTLINE_DOCS:
            break
    return trees


async def fetch_node_chunks(
    db: AsyncSession,
    org_id: uuid.UUID,
    kb_ids: list[uuid.UUID],
    filters: RetrievalFilters | None,
    trees: dict[str, tuple[Document, list[TreeNode]]],
    selected: list[tuple[str, TreeNode]],
    limit: int,
    method: str,
    scope: AccessScope | None = None,
) -> list[RetrievedChunk]:
    """Loads the real source chunks under the selected tree nodes. Filters
    (org, KB, freshness, authority) are re-applied here, so they hold no
    matter how the nodes were chosen."""
    wanted: list[tuple[uuid.UUID, int]] = []
    for doc_key, node in selected:
        doc = trees[doc_key][0]
        wanted.extend((doc.id, i) for i in subtree_chunk_indices(node))
    if not wanted:
        return []

    stmt = (
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.organization_id == org_id,
            Chunk.knowledge_base_id.in_(kb_ids),
            tuple_(Chunk.document_id, Chunk.chunk_index).in_(wanted),
        )
    )
    stmt = apply_common_filters(stmt, filters, scope)
    stmt = stmt.order_by(Chunk.document_id, Chunk.chunk_index).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [row_to_retrieved_chunk(c, d, TREE_BASE_SCORE, method) for c, d in rows]


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()
