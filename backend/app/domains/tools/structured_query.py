"""structured_query: filter/aggregate the rows of a tabular document (CSV, JSON record list).

There is no SQL for a model to write. A query is a document title, up to MAX_FILTERS
filters (column, allow-listed operator, value) and one aggregate, and is executed as a fully
parameterized query. Column names are checked against the document's real columns, values are
bound parameters, and numeric comparisons only look at cells that are actually numbers. The
document is found through the same org / knowledge-base / access filters as any retrieval.

The result is returned as a deterministic evidence chunk that cites the source document, so
a computed figure ("total for EU = 1234") is traceable to real rows rather than model output.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Numeric, case, cast, func, not_, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from app.domains.ingestion.chunkers.table import rows_to_markdown
from app.domains.ingestion.records import typed_value
from app.domains.retrieval.filters import apply_common_filters
from app.domains.retrieval.schemas import RetrievedChunk
from app.domains.tools.base import Tool, ToolContext, ToolResult
from app.domains.tools.search_tools import _escape_like
from app.models.document import Document, FileType
from app.models.document_row import DocumentRow

MAX_FILTERS = 5
SAMPLE_ROWS = 5
RESULT_SCORE = 0.85

Op = Literal["eq", "neq", "gt", "gte", "lt", "lte", "contains"]
Aggregate = Literal["count", "sum", "avg", "min", "max"]
_SYMBOL = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "contains": "contains"}


class QueryFilter(BaseModel):
    column: str = Field(min_length=1, max_length=60)
    op: Op
    value: int | float | str


class StructuredQueryTool(Tool):
    name: ClassVar[str] = "structured_query"
    description: ClassVar[str] = (
        "count/sum/average/min/max over the rows of a CSV or JSON table, optionally filtered "
        "(ops: eq, neq, gt, gte, lt, lte, contains)"
    )
    max_calls_per_run: ClassVar[int] = 3

    class Args(BaseModel):
        document_title: str = Field(min_length=2, max_length=200)
        aggregate: Aggregate = "count"
        column: str | None = Field(default=None, max_length=60)
        filters: list[QueryFilter] = Field(default_factory=list, max_length=MAX_FILTERS)

    async def run(self, ctx: ToolContext, args: Any) -> ToolResult:
        doc = await self._find_document(ctx, args.document_title)
        if doc is None:
            return ToolResult(content="no tabular document with that title")

        columns: list[str] = list((doc.parsing_metadata or {}).get("column_names") or [])
        by_lower = {c.lower(): c for c in columns}

        def canonical(name: str) -> str | None:
            return by_lower.get(name.strip().lower())

        if args.aggregate != "count" and not args.column:
            return ToolResult(ok=False, error=f"'{args.aggregate}' needs a column")
        agg_col = None
        if args.column:
            agg_col = canonical(args.column)
            if agg_col is None:
                return ToolResult(ok=False, error=self._unknown_column(args.column, columns))

        jb = cast(DocumentRow.data, JSONB)
        conditions = [
            DocumentRow.document_id == doc.id,
            DocumentRow.organization_id == ctx.org_id,
        ]
        shown_filters: list[str] = []
        for f in args.filters:
            col = canonical(f.column)
            if col is None:
                return ToolResult(ok=False, error=self._unknown_column(f.column, columns))
            cond = self._condition(jb, col, f)
            if isinstance(cond, str):
                return ToolResult(ok=False, error=cond)
            conditions.append(cond)
            shown_filters.append(f"{col} {_SYMBOL[f.op]} {f.value!r}")

        total = (
            await ctx.db.execute(
                select(func.count()).select_from(DocumentRow).where(
                    DocumentRow.document_id == doc.id, DocumentRow.organization_id == ctx.org_id
                )
            )
        ).scalar_one()
        matching = (
            await ctx.db.execute(select(func.count()).select_from(DocumentRow).where(*conditions))
        ).scalar_one()

        value: float | int | None = matching
        if args.aggregate != "count":
            num = self._numeric(jb, agg_col)
            fn = {"sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}[args.aggregate]
            raw = (await ctx.db.execute(select(fn(num)).where(*conditions))).scalar_one()
            value = None if raw is None else float(raw)
            if value is not None and value == int(value) and args.aggregate != "avg":
                value = int(value)

        samples = (
            await ctx.db.execute(
                select(DocumentRow.data).where(*conditions).order_by(DocumentRow.row_index)
                .limit(SAMPLE_ROWS)
            )
        ).scalars().all()

        return ToolResult(
            content=f"{args.aggregate} = {value} ({matching} of {total} rows)",
            chunks=[self._evidence(doc, args, shown_filters, agg_col, value, matching, total,
                                   columns, samples)],
        )

    # -- helpers ------------------------------------------------------------------------

    async def _find_document(self, ctx: ToolContext, title: str) -> Document | None:
        stmt = select(Document).where(
            Document.organization_id == ctx.org_id,
            Document.knowledge_base_id.in_(ctx.kb_ids),
            Document.file_type.in_([FileType.csv, FileType.json]),
            Document.title.ilike(f"%{_escape_like(title.strip())}%", escape="\\"),
        )
        stmt = apply_common_filters(stmt, ctx.filters, ctx.scope)
        stmt = stmt.order_by(func.length(Document.title), Document.id).limit(1)
        return (await ctx.db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _unknown_column(name: str, columns: list[str]) -> str:
        return f"unknown column '{name[:60]}'. Columns: {', '.join(columns) or '(none)'}"

    @staticmethod
    def _numeric(jb, column: str):
        cell = jb[column]
        # Only true JSON numbers are cast; text cells become NULL instead of raising.
        return case((func.jsonb_typeof(cell) == "number", cast(cell.astext, Numeric)), else_=None)

    def _condition(self, jb, column: str, f: QueryFilter):
        text = func.lower(jb[column].astext)
        num = self._numeric(jb, column)
        as_number = typed_value(f.value) if isinstance(f.value, str) else f.value
        is_number = isinstance(as_number, (int, float)) and not isinstance(as_number, bool)

        if f.op == "contains":
            if not isinstance(f.value, str):
                return "'contains' needs a text value"
            return text.contains(f.value.lower(), autoescape=True)

        if f.op in ("eq", "neq"):
            if isinstance(f.value, str):
                match = text == f.value.lower()
                if is_number:  # "12" should also match a numeric cell 12
                    match = or_(match, num == as_number)
            else:
                match = num == f.value
            return match if f.op == "eq" else not_(match)

        if not is_number:
            return f"'{f.op}' needs a numeric value"
        return {"gt": num > as_number, "gte": num >= as_number,
                "lt": num < as_number, "lte": num <= as_number}[f.op]

    def _evidence(self, doc, args, shown_filters, agg_col, value, matching, total, columns,
                  samples) -> RetrievedChunk:
        target = f"{args.aggregate}({agg_col})" if agg_col else args.aggregate
        where = f" where {' and '.join(shown_filters)}" if shown_filters else ""
        lines = [
            f'Structured query over "{doc.title}": {target}{where} = {value} '
            f"({matching} of {total} rows match)."
        ]
        if samples:
            rows = [columns, *[[str(r.get(c, "")) for c in columns] for r in samples]]
            lines += ["", f"First {len(samples)} matching rows:", rows_to_markdown(rows)]
        spec = json.dumps(args.model_dump(mode="json"), sort_keys=True)
        return RetrievedChunk(
            chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{doc.id}:{spec}"),
            document_id=doc.id,
            document_title=doc.title,
            content="\n".join(lines),
            score=RESULT_SCORE,
            metadata={
                "derived_from": ["structured_query"],
                "content_type": "structured_result",
                "source": "internal",
            },
            retrieval_method="structured",
            is_current=doc.is_current,
            authority_tier=doc.authority_tier.value,
            document_version=doc.version,
            effective_date=doc.effective_date,
        )
