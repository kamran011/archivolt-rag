from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage


class TextParser(BaseParser):
    """Heuristic structure detection for plain text (and used as a fallback for
    HTML/CSV/JSON until dedicated parsers are added)."""

    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        elements: list[DocumentElement] = []
        for para in paragraphs:
            lines = para.split("\n")
            first_line = lines[0].strip()

            # Heuristic: short, all-caps or title-case single line -> heading
            is_heading = (
                len(lines) == 1
                and len(first_line) < 100
                and (first_line.isupper() or first_line.endswith(":"))
            )
            if is_heading:
                elements.append(DocumentElement(type="heading", content=first_line, level=2))
            else:
                elements.append(DocumentElement(type="paragraph", content=para))

        title = file_name.rsplit(".", 1)[0]

        return ParsedDocument(
            title=title,
            pages=[ParsedPage(page_number=1, elements=elements)],
            metadata={"source": "text"},
        )
