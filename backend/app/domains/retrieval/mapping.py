from app.domains.retrieval.schemas import RetrievedChunk
from app.models.chunk import Chunk
from app.models.document import Document


def row_to_retrieved_chunk(
    chunk: Chunk,
    document: Document,
    score: float,
    retrieval_method: str,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_title=document.title,
        content=chunk.content,
        score=float(score),
        metadata={**(chunk.metadata_ or {}), "chunk_index": chunk.chunk_index},
        retrieval_method=retrieval_method,
        is_current=document.is_current,
        authority_tier=document.authority_tier.value,
        document_version=document.version,
        effective_date=document.effective_date,
    )
