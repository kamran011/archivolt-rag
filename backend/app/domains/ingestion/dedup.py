"""Content-hash helpers for ingestion: incremental re-embedding and near-duplicate detection.

Both work from a per-chunk content hash. Re-embedding reuses the vectors of identical
chunks from the version a document supersedes; near-duplicate detection compares a new
document's chunk hashes against the other current documents in its knowledge base.
Neither changes what a reader sees (document-level versioning stays the source of truth)."""

import hashlib
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document

_WS_RE = re.compile(r"\s+")


def content_hash(text: str) -> str:
    """sha256 of the whitespace-normalized text, so re-flowed but identical content matches."""
    return hashlib.sha256(_WS_RE.sub(" ", text).strip().encode("utf-8")).hexdigest()


def overlap_ratio(new_hashes: list[str], existing_hashes: set[str]) -> float:
    """Fraction of the new document's chunks whose content already exists elsewhere."""
    if not new_hashes:
        return 0.0
    return sum(1 for h in new_hashes if h in existing_hashes) / len(new_hashes)


async def load_reusable_embeddings(
    db: AsyncSession, previous_document_id: uuid.UUID | None, hashes: list[str]
) -> dict[str, list[float]]:
    """hash -> embedding for chunks of the superseded version whose content is unchanged."""
    if previous_document_id is None or not hashes:
        return {}
    result = await db.execute(
        select(Chunk.content_hash, Chunk.embedding).where(
            Chunk.document_id == previous_document_id,
            Chunk.content_hash.in_(set(hashes)),
            Chunk.embedding.is_not(None),
        )
    )
    return {h: emb for h, emb in result.all()}


async def find_near_duplicates(
    db: AsyncSession,
    document: Document,
    hashes: list[str],
    threshold: float,
    limit: int = 5,
) -> list[dict]:
    """Other current documents in the same KB sharing >= threshold of this document's chunks.

    The version being superseded is excluded: a new version is expected to overlap it."""
    if not hashes:
        return []
    unique = set(hashes)
    stmt = (
        select(Chunk.document_id, Chunk.content_hash, Document.file_name)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.knowledge_base_id == document.knowledge_base_id,
            Chunk.organization_id == document.organization_id,
            Chunk.document_id != document.id,
            Chunk.content_hash.in_(unique),
            Document.is_current.is_(True),
        )
    )
    if document.supersedes_document_id:
        stmt = stmt.where(Chunk.document_id != document.supersedes_document_id)
    rows = (await db.execute(stmt)).all()

    by_doc: dict[uuid.UUID, tuple[str, set[str]]] = {}
    for doc_id, h, name in rows:
        by_doc.setdefault(doc_id, (name, set()))[1].add(h)

    matches = []
    for doc_id, (name, shared) in by_doc.items():
        ratio = overlap_ratio(hashes, shared)
        if ratio >= threshold:
            matches.append(
                {"document_id": str(doc_id), "file_name": name, "overlap": round(ratio, 3)}
            )
    matches.sort(key=lambda m: m["overlap"], reverse=True)
    return matches[:limit]
