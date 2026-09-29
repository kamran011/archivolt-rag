"""JSON -> outline. Objects become headings (one level per nesting level, keyed by field
name) with scalar fields as "key: value" lines; lists of records become tables. Depth and size
are bounded, and invalid JSON fails ingestion with a clear error rather than being indexed
as garbage text."""

import json
from typing import Any

from app.core.exceptions import IngestionError
from app.domains.ingestion.chunkers.table import rows_to_markdown
from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage

MAX_DEPTH = 8
MAX_ELEMENTS = 20_000
MAX_VALUE_CHARS = 2_000


def _scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)[:MAX_VALUE_CHARS]


def _is_record_list(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) > 0
        and all(isinstance(i, dict) for i in v)
        and all(not isinstance(x, (dict, list)) for i in v for x in i.values())
    )


class _Walker:
    def __init__(self) -> None:
        self.elements: list[DocumentElement] = []

    def _add(self, el: DocumentElement) -> None:
        if len(self.elements) >= MAX_ELEMENTS:
            raise IngestionError("JSON is too large to index (too many elements)")
        self.elements.append(el)

    def walk(self, value: Any, key: str, depth: int) -> None:
        level = min(depth + 1, 6)
        if depth > MAX_DEPTH:
            self._add(DocumentElement(type="paragraph", content=f"{key}: {_scalar(value)}"))
            return
        if isinstance(value, dict):
            self._add(DocumentElement(type="heading", content=key, level=level))
            scalars = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
            if scalars:
                self._add(
                    DocumentElement(
                        type="paragraph",
                        content="\n".join(f"{k}: {_scalar(v)}" for k, v in scalars.items()),
                    )
                )
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    self.walk(v, str(k), depth + 1)
        elif _is_record_list(value):
            self._add(DocumentElement(type="heading", content=key, level=level))
            cols = list(dict.fromkeys(c for rec in value for c in rec))
            rows = [cols] + [[_scalar(rec.get(c, "")) for c in cols] for rec in value]
            self._add(DocumentElement(type="table", content=rows_to_markdown(rows)))
        elif isinstance(value, list):
            self._add(DocumentElement(type="heading", content=key, level=level))
            for i, item in enumerate(value):
                if isinstance(item, (dict, list)):
                    self.walk(item, f"{key}[{i}]", depth + 1)
                else:
                    self._add(
                        DocumentElement(type="list", content=f"- {_scalar(item)}")
                    )
        else:
            self._add(DocumentElement(type="paragraph", content=f"{key}: {_scalar(value)}"))


class JSONParser(BaseParser):
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as e:
            raise IngestionError(f"Invalid JSON: {e}") from e

        title = file_name.rsplit(".", 1)[0]
        walker = _Walker()
        walker.walk(data, title, 0)
        if not walker.elements:
            raise IngestionError("JSON contains no content")
        return ParsedDocument(
            title=title,
            pages=[ParsedPage(page_number=1, elements=walker.elements)],
            metadata={"source": "json"},
        )
