"""Document-level access control, applied inside the SQL of every retrieval path.

A restricted document is visible to: org owners/admins, the user who uploaded it, and
users granted access in `document_access`. Everyone else never has it retrieved — it is
excluded by the query itself, not filtered out of results afterwards, so it cannot reach
reranking, context assembly or the LLM.

Fail closed: when no AccessScope is supplied, restricted documents are excluded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, or_, select, true

from app.models.document import Document, DocumentAccess


@dataclass(frozen=True)
class AccessScope:
    user_id: uuid.UUID | None
    is_admin: bool = False


@dataclass(frozen=True)
class Actor:
    """Who is making an agentic request, for tool authorization. Derived from the
    authenticated user and the organization row — never from request input."""

    user_id: uuid.UUID | None
    role: object | None = None  # OrgRole
    org_settings: dict = field(default_factory=dict)


def actor_for(user, org_settings: dict | None = None) -> Actor:
    return Actor(user_id=user.id, role=user.role, org_settings=dict(org_settings or {}))


# For internal, non-user-facing callers (never build one from request data).
SYSTEM_SCOPE = AccessScope(user_id=None, is_admin=True)


def scope_for(user) -> AccessScope:
    """Derive the retrieval scope from the *authenticated* user (never from client input)."""
    from app.models.organization_member import OrgRole

    return AccessScope(user_id=user.id, is_admin=user.role in (OrgRole.owner, OrgRole.admin))


def visible_document_clause(scope: AccessScope | None) -> ColumnElement[bool]:
    open_docs = Document.restricted.is_(False)
    if scope is None:
        return open_docs
    clauses = [open_docs]
    if scope.is_admin:
        return true()  # admins see everything in their org (queries are still org-scoped)
    if scope.user_id is not None:
        clauses.append(Document.uploaded_by == scope.user_id)
        clauses.append(
            Document.id.in_(
                select(DocumentAccess.document_id).where(DocumentAccess.user_id == scope.user_id)
            )
        )
    return or_(*clauses)
