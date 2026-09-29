from typing import Literal

from pydantic import BaseModel, Field

ElementType = Literal["heading", "paragraph", "list", "table", "code", "image_caption"]


class DocumentElement(BaseModel):
    type: ElementType
    content: str
    level: int | None = None  # heading level (1-6)
    page_number: int | None = None
    metadata: dict = Field(default_factory=dict)


class ParsedPage(BaseModel):
    page_number: int
    elements: list[DocumentElement]


class ParsedDocument(BaseModel):
    title: str
    pages: list[ParsedPage]
    metadata: dict = Field(default_factory=dict)

    def all_elements(self) -> list[DocumentElement]:
        elements: list[DocumentElement] = []
        for page in self.pages:
            elements.extend(page.elements)
        return elements


class ChunkData(BaseModel):
    content: str
    chunk_index: int
    token_count: int
    metadata: dict = Field(default_factory=dict)


class IngestionStatusResponse(BaseModel):
    document_id: str
    status: str
    progress_message: str | None = None
    error_message: str | None = None
