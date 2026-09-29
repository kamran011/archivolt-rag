import re

from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.schemas import DocumentElement, ParsedDocument, ParsedPage

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
CODE_FENCE_RE = re.compile(r"^```")
LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+")


class MarkdownParser(BaseParser):
    async def parse(self, content: bytes, file_name: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        lines = text.split("\n")

        elements: list[DocumentElement] = []
        buffer: list[str] = []
        in_code_block = False
        code_buffer: list[str] = []
        title = file_name.rsplit(".", 1)[0]
        found_title = False

        def flush_paragraph():
            if buffer:
                para_text = "\n".join(buffer).strip()
                if para_text:
                    el_type = "list" if LIST_ITEM_RE.match(buffer[0]) else "paragraph"
                    elements.append(DocumentElement(type=el_type, content=para_text))
                buffer.clear()

        for line in lines:
            if CODE_FENCE_RE.match(line.strip()):
                if in_code_block:
                    elements.append(
                        DocumentElement(type="code", content="\n".join(code_buffer))
                    )
                    code_buffer = []
                    in_code_block = False
                else:
                    flush_paragraph()
                    in_code_block = True
                continue

            if in_code_block:
                code_buffer.append(line)
                continue

            heading_match = HEADING_RE.match(line)
            if heading_match:
                flush_paragraph()
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()
                elements.append(
                    DocumentElement(type="heading", content=heading_text, level=level)
                )
                if not found_title and level == 1:
                    title = heading_text
                    found_title = True
                continue

            if line.strip() == "":
                flush_paragraph()
                continue

            buffer.append(line)

        flush_paragraph()

        return ParsedDocument(
            title=title,
            pages=[ParsedPage(page_number=1, elements=elements)],
            metadata={"source": "markdown"},
        )
