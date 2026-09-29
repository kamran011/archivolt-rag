from app.domains.ingestion.chunkers.base import BaseChunker
from app.domains.ingestion.chunkers.fixed_chunker import FixedChunker
from app.domains.ingestion.chunkers.table import split_table
from app.domains.ingestion.schemas import ChunkData, DocumentElement, ParsedDocument, ParsedPage


class StructureAwareChunker(BaseChunker):
    """
    Groups content under its heading hierarchy. Each section becomes a chunk
    if it fits the token budget; oversized sections fall back to fixed chunking.
    Heading hierarchy is prepended to chunk content as navigational context.
    """

    def __init__(self) -> None:
        self._fallback = FixedChunker()

    def chunk(
        self,
        parsed: ParsedDocument,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkData]:
        sections = self._group_by_headings(parsed)

        chunks: list[ChunkData] = []
        chunk_index = 0

        runs = [
            (hierarchy, run, run_page)
            for hierarchy, elements, page_num in sections
            for run, run_page in self._split_runs(elements, page_num)
        ]

        for hierarchy, elements, page_num in runs:
            if len(elements) == 1 and elements[0].type == "table":
                for piece in split_table(
                    elements[0].content, chunk_size, self.count_tokens
                ):
                    prefix = self._format_hierarchy(hierarchy)
                    content = f"{prefix}\n\n{piece}" if prefix else piece
                    chunks.append(
                        ChunkData(
                            content=content,
                            chunk_index=chunk_index,
                            token_count=self.count_tokens(content),
                            metadata={
                                "heading_hierarchy": hierarchy,
                                "page_number": page_num,
                                "section_types": ["table"],
                                "content_type": "table",
                            },
                        )
                    )
                    chunk_index += 1
                continue

            section_text_parts = [el.content for el in elements if el.type != "heading"]
            section_body = "\n\n".join(section_text_parts).strip()

            if not section_body:
                continue

            prefix = self._format_hierarchy(hierarchy)
            full_content = f"{prefix}\n\n{section_body}" if prefix else section_body
            token_count = self.count_tokens(full_content)

            section_types = list({el.type for el in elements})
            derived = [el.metadata["derived_from"] for el in elements if "derived_from" in el.metadata]
            extra_meta = {"derived_from": sorted(set(derived))} if derived else {}

            if token_count <= chunk_size:
                chunks.append(
                    ChunkData(
                        content=full_content,
                        chunk_index=chunk_index,
                        token_count=token_count,
                        metadata={
                            "heading_hierarchy": hierarchy,
                            "page_number": page_num,
                            "section_types": section_types,
                            **extra_meta,
                        },
                    )
                )
                chunk_index += 1
            else:
                # Oversized section: fall back to fixed chunking within this section
                sub_doc = ParsedDocument(
                    title=parsed.title,
                    pages=[ParsedPage(page_number=page_num or 1, elements=elements)],
                )
                sub_chunks = self._fallback.chunk(sub_doc, chunk_size, chunk_overlap)
                for sub in sub_chunks:
                    prefixed = f"{prefix}\n\n{sub.content}" if prefix else sub.content
                    chunks.append(
                        ChunkData(
                            content=prefixed,
                            chunk_index=chunk_index,
                            token_count=self.count_tokens(prefixed),
                            metadata={
                                "heading_hierarchy": hierarchy,
                                "page_number": sub.metadata.get("page_number", page_num),
                                "section_types": section_types,
                                "split_from_oversized_section": True,
                                # keep how the sub-chunk was made (e.g. semantic_split)
                                **{k: v for k, v in sub.metadata.items() if k != "page_number"},
                                **extra_meta,
                            },
                        )
                    )
                    chunk_index += 1

        # Document had no headings at all — fall back entirely
        if not chunks:
            return self._fallback.chunk(parsed, chunk_size, chunk_overlap)

        return chunks

    def _split_runs(
        self, elements: list[DocumentElement], page_num: int | None
    ) -> list[tuple[list[DocumentElement], int | None]]:
        """Splits a section into runs so each table is chunked on its own
        (never merged into or cut by surrounding prose)."""
        runs: list[tuple[list[DocumentElement], int | None]] = []
        current: list[DocumentElement] = []
        for el in elements:
            if el.type == "table":
                if current:
                    runs.append((current, page_num))
                    current = []
                runs.append(([el], el.page_number or page_num))
            else:
                current.append(el)
        if current:
            runs.append((current, page_num))
        return runs

    def _group_by_headings(
        self, parsed: ParsedDocument
    ) -> list[tuple[list[str], list[DocumentElement], int | None]]:
        """Returns list of (heading_hierarchy, elements_in_section, page_number)."""
        sections: list[tuple[list[str], list[DocumentElement], int | None]] = []
        hierarchy_stack: list[tuple[int, str]] = []  # (level, text)
        current_elements: list[DocumentElement] = []
        current_page: int | None = None

        def current_hierarchy() -> list[str]:
            return [text for _, text in hierarchy_stack]

        def flush():
            if current_elements:
                sections.append((current_hierarchy(), list(current_elements), current_page))

        for page in parsed.pages:
            for el in page.elements:
                if el.type == "heading":
                    flush()
                    current_elements.clear()
                    level = el.level or 1
                    # Pop stack entries at same or deeper level
                    while hierarchy_stack and hierarchy_stack[-1][0] >= level:
                        hierarchy_stack.pop()
                    hierarchy_stack.append((level, el.content))
                    current_page = el.page_number or page.page_number
                else:
                    current_elements.append(el)
                    if current_page is None:
                        current_page = el.page_number or page.page_number

        flush()
        return sections

    def _format_hierarchy(self, hierarchy: list[str]) -> str:
        if not hierarchy:
            return ""
        return "# " + " > ".join(hierarchy)
