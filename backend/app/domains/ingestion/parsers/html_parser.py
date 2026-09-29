"""HTML -> structured document (headings, paragraphs, lists, tables, code, captions).

Uses the standard-library HTMLParser: nothing is executed or fetched. <script>, <style>,
templates, forms and other non-content elements are dropped entirely, so markup that tries
to smuggle instructions through hidden elements does not become evidence.
"""

from html.parser import HTMLParser

from app.core.exceptions import IngestionError
from app.domains.ingestion.chunkers.table import rows_to_markdown
from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage

_SKIP = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "embed",
    "form", "select", "option", "button", "nav", "footer", "head",
}
_HEADINGS = {f"h{i}": i for i in range(1, 7)}
_BLOCK = {
    "p", "div", "section", "article", "main", "aside", "blockquote", "header", "figure",
    "address", "dd", "dt", "summary", "details",
}
MAX_DEPTH = 200  # guard against pathological nesting


def _clean(text: str) -> str:
    return " ".join(text.split())


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[DocumentElement] = []
        self.title = ""
        self._skip_depth = 0
        self._depth = 0
        self._buf: list[str] = []
        self._buf_kind: str | None = None  # paragraph | heading | code | caption
        self._heading_level = 2
        self._list_items: list[str] = []
        self._in_li = False
        self._in_title = False
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._pre = 0

    # -- buffering --------------------------------------------------------------
    def _flush(self) -> None:
        text = "".join(self._buf)
        kind = self._buf_kind
        self._buf, self._buf_kind = [], None
        text = text.strip("\n") if kind == "code" else _clean(text)
        if not text:
            return
        if kind == "heading":
            self.elements.append(
                DocumentElement(type="heading", content=text, level=self._heading_level)
            )
        elif kind == "code":
            self.elements.append(DocumentElement(type="code", content=text))
        elif kind == "caption":
            self.elements.append(DocumentElement(type="image_caption", content=text))
        else:
            self.elements.append(DocumentElement(type="paragraph", content=text))

    def _flush_list(self) -> None:
        if self._list_items:
            self.elements.append(
                DocumentElement(
                    type="list", content="\n".join(f"- {i}" for i in self._list_items)
                )
            )
        self._list_items = []

    # -- HTMLParser hooks ---------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        self._depth += 1
        if self._skip_depth or tag in _SKIP or self._depth > MAX_DEPTH:
            if tag in _SKIP or self._skip_depth:
                self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag in _HEADINGS:
            self._flush()
            self._flush_list()
            self._buf_kind, self._heading_level = "heading", _HEADINGS[tag]
        elif tag == "pre":
            self._flush()
            self._buf_kind, self._pre = "code", self._pre + 1
        elif tag in ("ul", "ol"):
            self._flush()
        elif tag == "li":
            self._flush()
            self._in_li = True
            self._buf_kind = "list"
        elif tag == "table":
            self._flush()
            self._flush_list()
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "figcaption":
            self._flush()
            self._buf_kind = "caption"
        elif tag == "img":
            alt = _clean(dict(attrs).get("alt") or "")
            if alt:
                self._flush()
                self.elements.append(DocumentElement(type="image_caption", content=alt))
        elif tag == "br" and self._cell is None:
            self._buf.append("\n" if self._pre else " ")
        elif tag in _BLOCK:
            self._flush()
            self._flush_list()

    def handle_endtag(self, tag):
        self._depth = max(0, self._depth - 1)
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        elif tag in _HEADINGS:
            self._flush()
            if not self.title and self._heading_level == 1 and self.elements:
                self.title = self.elements[-1].content
        elif tag == "pre":
            self._flush()
            self._pre = max(0, self._pre - 1)
        elif tag == "li":
            text = _clean("".join(self._buf))
            self._buf, self._buf_kind, self._in_li = [], None, False
            if text:
                self._list_items.append(text)
        elif tag in ("ul", "ol"):
            self._flush_list()
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(_clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            md = rows_to_markdown(self._table)
            if md:
                self.elements.append(DocumentElement(type="table", content=md))
            self._table = None
        elif tag == "figcaption":
            self._flush()
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        elif self._cell is not None:
            self._cell.append(data)
        elif self._table is not None:
            return  # text between rows/cells is layout whitespace
        else:
            if self._buf_kind is None:
                self._buf_kind = "paragraph"
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()
        self._flush_list()


class HTMLDocumentParser(BaseParser):
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        extractor = _Extractor()
        try:
            extractor.feed(text)
            extractor.close()
        except Exception as e:
            raise IngestionError(f"Failed to parse HTML: {e}") from e

        if not extractor.elements:
            raise IngestionError("HTML contains no readable text")

        title = _clean(extractor.title) or file_name.rsplit(".", 1)[0]
        return ParsedDocument(
            title=title,
            pages=[ParsedPage(page_number=1, elements=extractor.elements)],
            metadata={"source": "html"},
        )
