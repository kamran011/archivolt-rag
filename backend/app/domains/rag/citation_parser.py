import re

from app.domains.rag.schemas import Citation
from app.domains.retrieval.schemas import RetrievedChunk

SOURCE_REF_RE = re.compile(r"\[Source (\d+)\]")


class CitationParser:
    @staticmethod
    def parse_citations(
        answer: str, chunks: list[RetrievedChunk]
    ) -> list[Citation]:
        """Extracts [Source N] references from the answer and maps them to the
        chunks that were actually supplied as evidence (1-indexed)."""
        referenced_indices = {int(m) for m in SOURCE_REF_RE.findall(answer)}

        citations: list[Citation] = []
        for idx in sorted(referenced_indices):
            # Only accept indices that correspond to real supplied evidence —
            # never trust a citation number the model invented.
            if 1 <= idx <= len(chunks):
                chunk = chunks[idx - 1]
                citations.append(
                    Citation(
                        index=idx,
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        document_title=chunk.document_title,
                        content=chunk.content,
                        page_number=chunk.metadata.get("page_number"),
                        relevance_score=chunk.score,
                    )
                )
        return citations
