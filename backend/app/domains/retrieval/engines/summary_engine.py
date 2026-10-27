"""Hierarchical summary retrieval: query -> document summaries -> section summaries ->
raw chunks.

Summaries only *navigate*: they pick candidate documents and then sections, and the result
is always the raw source chunks under those sections (the evidence), scored by the
similarity of the section summary that led to them. Access control and tenancy are applied
in the SQL of every step (shared filters + scope), so a summary of a document the caller
cannot see is never even a candidate.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.retrieval.access import AccessScope
from app.domains.retrieval.engines.base import RetrievalEngine
from app.domains.retrieval.engines.tree_engine import fetch_node_chunks, load_document_trees
from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.schemas import RetrievalFilters, RetrievedChunk
from app.domains.retrieval.tree import iter_nodes, subtree_chunk_indices
from app.models.document import Document
from app.models.summary import DocumentSummary
from app.providers.embeddings.query_memo import embed_query
from app.providers.embeddings.registry import get_embedding_provider

DOCUMENT_CANDIDATES = 5
SECTION_CANDIDATES = 6


class SummaryRetrievalEngine(RetrievalEngine):
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
        query_embedding = await embed_query(get_embedding_provider(embedding_model), query)

        # 1. candidate documents, by document-level summary
        doc_hits = await self._top(
            db, org_id, kb_ids, filters, scope, query_embedding, "document", DOCUMENT_CANDIDATES
        )
        if not doc_hits:
            return []
        doc_ids = [doc_id for doc_id, _, _ in doc_hits]

        # 2. candidate sections inside those documents, by section-level summary
        section_hits = await self._top(
            db, org_id, kb_ids, filters, scope, query_embedding, "section",
            SECTION_CANDIDATES, only_documents=doc_ids,
        )
        if not section_hits:
            return []

        # 3. the raw chunks under those sections. Reuses the tree machinery, which
        # re-applies org/KB/filter/scope conditions when loading chunks.
        narrowed = RetrievalFilters(
            **{**(filters.model_dump() if filters else {}), "document_ids": doc_ids}
        )
        trees = await load_document_trees(db, org_id, kb_ids, narrowed, scope)
        key_by_doc = {doc.id: key for key, (doc, _) in trees.items()}

        selected = []
        score_by_chunk: dict[tuple[uuid.UUID, int], float] = {}
        for doc_id, node_id, score in section_hits:
            key = key_by_doc.get(doc_id)
            if key is None:
                continue
            node = next((n for n in iter_nodes(trees[key][1]) if n.node_id == node_id), None)
            if node is None:
                continue
            selected.append((key, node))
            for idx in subtree_chunk_indices(node):
                k = (doc_id, idx)
                score_by_chunk[k] = max(score_by_chunk.get(k, 0.0), score)
        if not selected:
            return []

        chunks = await fetch_node_chunks(
            db, org_id, kb_ids, narrowed, trees, selected, top_k * 2, "summary", scope
        )
        rescored = [
            c.model_copy(
                update={"score": score_by_chunk.get((c.document_id, c.metadata.get("chunk_index")), 0.0)}
            )
            for c in chunks
        ]
        rescored.sort(key=lambda c: c.score, reverse=True)
        return rescored[:top_k]

    async def _top(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        kb_ids: list[uuid.UUID],
        filters: RetrievalFilters | None,
        scope: AccessScope | None,
        query_embedding: list[float],
        level: str,
        limit: int,
        only_documents: list[uuid.UUID] | None = None,
    ) -> list[tuple[uuid.UUID, str | None, float]]:
        distance = DocumentSummary.embedding.cosine_distance(query_embedding)
        stmt = (
            select(DocumentSummary.document_id, DocumentSummary.node_id, (1 - distance).label("s"))
            .join(Document, Document.id == DocumentSummary.document_id)
            .where(
                DocumentSummary.organization_id == org_id,
                DocumentSummary.knowledge_base_id.in_(kb_ids),
                DocumentSummary.level == level,
                DocumentSummary.embedding.is_not(None),
            )
        )
        if only_documents is not None:
            stmt = stmt.where(DocumentSummary.document_id.in_(only_documents))
        stmt = apply_common_filters(stmt, filters, scope)
        stmt = stmt.order_by(distance).limit(limit)
        return [(r.document_id, r.node_id, float(r.s)) for r in (await db.execute(stmt)).all()]
