from app.domains.ingestion.parsers.base import BaseParser
from app.domains.ingestion.parsers.csv_parser import CSVParser
from app.domains.ingestion.parsers.docx_parser import DocxParser
from app.domains.ingestion.parsers.html_parser import HTMLDocumentParser
from app.domains.ingestion.parsers.image_parser import ImageParser
from app.domains.ingestion.parsers.json_parser import JSONParser
from app.domains.ingestion.parsers.markdown_parser import MarkdownParser
from app.domains.ingestion.parsers.pdf_parser import PDFParser
from app.domains.ingestion.parsers.text_parser import TextParser
from app.models.document import FileType

_REGISTRY: dict[FileType, type[BaseParser]] = {
    FileType.pdf: PDFParser,
    FileType.docx: DocxParser,
    FileType.md: MarkdownParser,
    FileType.txt: TextParser,
    FileType.html: HTMLDocumentParser,
    FileType.csv: CSVParser,
    FileType.json: JSONParser,
    FileType.image: ImageParser,
}


def get_parser(file_type: FileType) -> BaseParser:
    parser_cls = _REGISTRY.get(file_type)
    if not parser_cls:
        raise ValueError(f"No parser registered for file type: {file_type}")
    return parser_cls()


__all__ = [
    "BaseParser",
    "CSVParser",
    "DocxParser",
    "HTMLDocumentParser",
    "ImageParser",
    "JSONParser",
    "MarkdownParser",
    "PDFParser",
    "TextParser",
    "get_parser",
]
