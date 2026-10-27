"""Correctness-safe answer cache (V2).

Not a TTL cache. An entry is served only if all of these hold:
1. The request is cacheable: stateless (no conversation history), internal evidence only
   (no agentic/web), and the cached answer was a real answer (never an abstention).
2. The key includes the org, KBs, normalized query, model, and the caller's access scope
   (a restricted-document answer is never replayed to someone who could not retrieve it).
3. Verify-on-hit: every cited document is still the current version and still visible to
   this caller. Checked against Postgres on each hit.
Entries are also evicted on write: reverse indexes document -> keys and KB -> keys are
cleared by `invalidate_document` / `invalidate_kb`, called from the document lifecycle.
TTL is only a backstop and is shortened when a cited document has been re-versioned.
"""

from __future__ import annotations

import hashlib
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cache import get_cache, safe
from app.domains.rag.schemas import RAGRequest, RAGResponse
from app.domains.retrieval.access import AccessScope, visible_document_clause
from app.models.document import Document

logger = structlog.get_logger()


def is_cacheable_request(request: RAGRequest) -> bool:
    return (
        settings.ENABLE_RESPONSE_CACHE
        and not request.agentic
        and not request.web_search
        and not request.conversation_history
    )


def _scope_fingerprint(scope: AccessScope | None) -> str:
    if scope is None:
        return "none"
    return "admin" if scope.is_admin else f"user:{scope.user_id}"


def cache_key(org_id: uuid.UUID, request: RAGRequest, scope: AccessScope | None) -> str:
    parts = [
        str(org_id),
        ",".join(sorted(str(k) for k in request.knowledge_base_ids)),
        " ".join(request.query.lower().split()),
        request.model,
        f"{request.temperature}",
        request.mode,
        _scope_fingerprint(scope),
    ]
    return "resp:" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _doc_index(doc_id: str) -> str:
    return f"idx:doc:{doc_id}"


def _kb_index(kb_id: str) -> str:
    return f"idx:kb:{kb_id}"


async def _verify(
    db: AsyncSession, org_id: uuid.UUID, scope: AccessScope | None, docs: dict[str, int]
) -> bool:
    """Cited documents are all still current, same version, and visible to the caller."""
    if not docs:
        return False
    ids = [uuid.UUID(d) for d in docs]
    rows = (
        await db.execute(
            select(Document.id, Document.version).where(
                Document.id.in_(ids),
                Document.organization_id == org_id,
                Document.is_current.is_(True),
                visible_document_clause(scope),
            )
        )
    ).all()
    return len(rows) == len(ids) and all(docs[str(i)] == v for i, v in rows)


async def lookup(
    db: AsyncSession,
    org_id: uuid.UUID,
    request: RAGRequest,
    scope: AccessScope | None,
) -> RAGResponse | None:
    cache = get_cache()
    key = cache_key(org_id, request, scope)
    entry = await safe(cache.get_json(key))
    if not entry:
        return None
    if not await _verify(db, org_id, scope, entry["docs"]):
        await safe(cache.delete(key))
        logger.info("response_cache_stale_on_hit", key=key[:16])
        return None
    response = RAGResponse.model_validate(entry["response"])
    # A hit costs nothing and has no trace of its own.
    response.retrieval_metadata = {
        **response.retrieval_metadata,
        "cache_hit": True,
        "estimated_cost_usd": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
    return response


async def store(
    db: AsyncSession,
    org_id: uuid.UUID,
    request: RAGRequest,
    scope: AccessScope | None,
    response: RAGResponse,
) -> None:
    if response.abstained or not response.citations:
        return
    if any(c.source_type != "internal" for c in response.citations):
        return
    doc_ids = {c.document_id for c in response.citations}
    versions = dict(
        (
            await db.execute(
                select(Document.id, Document.version).where(Document.id.in_(doc_ids))
            )
        ).all()
    )
    if set(versions) != doc_ids:
        return
    volatile = any(v > 1 for v in versions.values())
    ttl = settings.RESPONSE_CACHE_TTL_S
    if volatile:
        ttl = max(1, ttl // max(1, settings.RESPONSE_CACHE_VOLATILE_DIVISOR))

    cache = get_cache()
    key = cache_key(org_id, request, scope)
    entry = {
        "response": response.model_dump(mode="json"),
        "docs": {str(d): v for d, v in versions.items()},
    }
    await safe(cache.set_json(key, entry, ttl))
    for doc_id in versions:
        await safe(cache.sadd(_doc_index(str(doc_id)), key, ttl))
    for kb_id in request.knowledge_base_ids:
        await safe(cache.sadd(_kb_index(str(kb_id)), key, ttl))


async def invalidate_document(doc_id: uuid.UUID | str) -> int:
    return await safe(get_cache().invalidate_index(_doc_index(str(doc_id))), 0)


async def invalidate_kb(kb_id: uuid.UUID | str) -> int:
    return await safe(get_cache().invalidate_index(_kb_index(str(kb_id))), 0)


__all__ = ["cache_key", "invalidate_document", "invalidate_kb", "is_cacheable_request", "lookup", "store"]
