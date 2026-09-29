"""CSV/TSV -> one table element (header row + data rows).

The structure-aware chunker splits tables on row boundaries and repeats the header on every
piece, so each chunk stays self-describing. Row/column counts are capped so a huge export
cannot exhaust memory or produce an unbounded number of chunks.
"""

import csv
import io

from app.core.exceptions import IngestionError
from app.domains.ingestion.chunkers.table import rows_to_markdown
from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage

MAX_ROWS = 20_000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 2_000


def _dialect(sample: str) -> type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


class CSVParser(BaseParser):
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        text = content.decode("utf-8-sig", errors="replace")
        if not text.strip():
            raise IngestionError("CSV is empty")

        csv.field_size_limit(MAX_CELL_CHARS * 10)
        reader = csv.reader(io.StringIO(text), _dialect(text[:8192]))
        rows: list[list[str]] = []
        truncated = False
        try:
            for i, row in enumerate(reader):
                if i >= MAX_ROWS + 1:  # +1 for the header
                    truncated = True
                    break
                rows.append([c[:MAX_CELL_CHARS] for c in row[:MAX_COLUMNS]])
        except csv.Error as e:
            raise IngestionError(f"Failed to parse CSV: {e}") from e

        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            raise IngestionError("CSV contains no data")

        table = rows_to_markdown(rows)
        title = file_name.rsplit(".", 1)[0]
        return ParsedDocument(
            title=title,
            pages=[
                ParsedPage(
                    page_number=1,
                    elements=[
                        DocumentElement(
                            type="table",
                            content=table,
                            metadata={"columns": rows[0], "rows": len(rows) - 1},
                        )
                    ],
                )
            ],
            metadata={
                "source": "csv",
                "rows": len(rows) - 1,
                "columns": len(rows[0]),
                "truncated": truncated,
            },
        )
