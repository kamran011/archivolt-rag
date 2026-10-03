"""Evidence tools over the internal knowledge base. Both are read-only, org/KB/access
scoped through ToolContext (never through arguments), and return real source chunks."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.mapping import row_to_retrieved_chunk
from app.domains.retrieval.schemas import RetrievalRequest
from app.domains.retrieval.service import retrieval_service
from app.domains.tools.base import Tool, ToolContext, ToolResult
from app.models.chunk import Chunk
from app.models.document import Document

SEARCH_TOP_K = 10
LOOKUP_CHUNK_LIMIT = 8
LOOKUP_BASE_SCORE = 0.8


def _summarize(chunks) -> str:
    docs = len({c.document_id for c in chunks})
    return f"{len(chunks)} passages from {docs} documents"


class KnowledgeBaseSearchTool(Tool):
    name: ClassVar[str] = "knowledge_base_search"
    description: ClassVar[str] = "search the knowledge base for passages relevant to a query"
    max_calls_per_run: ClassVar[int] = 6

    class Args(BaseModel):
        query: str = Field(min_length=1, max_length=300)
        strategy: Literal["hybrid", "semantic", "keyword"] = "hybrid"

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        result = await retrieval_service.retrieve(
            ctx.db,
            ctx.org_id,
            RetrievalRequest(
                query=args.query.strip(),
                knowledge_base_ids=ctx.kb_ids,
                strategy=args.strategy,
                top_k=SEARCH_TOP_K,
                filters=ctx.filters,
            ),
            scope=ctx.scope,
        )
        return ToolResult(content=_summarize(result.chunks), chunks=result.chunks)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DocumentLookupTool(Tool):
    name: ClassVar[str] = "document_lookup"
    description: ClassVar[str] = (
        "open a specific document by (part of) its title and read its first passages"
    )
    max_calls_per_run: ClassVar[int] = 3

    class Args(BaseModel):
        title: str = Field(min_length=2, max_length=200)

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        pattern = f"%{_escape_like(args.title.strip())}%"
        stmt = (
            select(Chunk, Document)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.organization_id == ctx.org_id,
                Chunk.knowledge_base_id.in_(ctx.kb_ids),
                Document.title.ilike(pattern, escape="\\"),
            )
        )
        stmt = apply_common_filters(stmt, ctx.filters, ctx.scope)
        # Prefer the best title match (shortest containing title), then reading order.
        stmt = stmt.order_by(func.length(Document.title), Document.id, Chunk.chunk_index)
        rows = (await ctx.db.execute(stmt)).all()
        if not rows:
            return ToolResult(content="no document with that title", chunks=[])
        first_doc = rows[0][1].id
        chunks = [
            row_to_retrieved_chunk(c, d, LOOKUP_BASE_SCORE, "lookup")
            for c, d in rows
            if d.id == first_doc
        ][:LOOKUP_CHUNK_LIMIT]
        return ToolResult(content=f"opened '{rows[0][1].title}': {len(chunks)} passages", chunks=chunks)
