"""
Cross-tenant isolation tests (master spec section 37).

These run against a real (in-memory SQLite) database rather than mocks —
proving the authorization boundary at the query level, not just asserting
that code "looks right". SQLite is used because it can host every table
except `chunks` (which needs pgvector + TSVECTOR, Postgres-only types).
Vector/keyword retrieval isolation is instead covered by
test_retrieval_query_isolation.py, which asserts the compiled SQL always
filters by organization_id — a real Postgres/Supabase run should still
be used to verify this end-to-end before production use.
"""

import time
import uuid

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.domains.auth.dependencies import get_current_user
from app.domains.knowledge_bases.schemas import KBCreate
from app.domains.knowledge_bases.service import KnowledgeBaseService
from app.domains.organizations.schemas import OrgCreate
from app.domains.organizations.service import OrganizationService
from app.models.base import Base
from app.models.knowledge_base import KnowledgeBase
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember


@pytest_asyncio.fixture
async def sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Organization.__table__,
        OrganizationMember.__table__,
        KnowledgeBase.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def make_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "email": "user@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class FakeCredentials:
    def __init__(self, token: str):
        self.credentials = token


@pytest.mark.asyncio
async def test_get_current_user_rejects_org_with_no_membership_row(sqlite_session):
    """User A has no membership in org B at all — must be rejected even
    though org B genuinely exists in the database."""
    org_service = OrganizationService()
    user_a = uuid.uuid4()

    await org_service.create(sqlite_session, user_a, OrgCreate(name="Org A", slug="org-a"))
    org_b = await org_service.create(sqlite_session, uuid.uuid4(), OrgCreate(name="Org B", slug="org-b"))
    await sqlite_session.commit()

    token = make_token(user_a)

    with pytest.raises(ForbiddenError):
        await get_current_user(
            credentials=FakeCredentials(token),
            x_organization_id=str(org_b.id),
            db=sqlite_session,
        )


@pytest.mark.asyncio
async def test_get_current_user_rejects_forged_nonexistent_org_id(sqlite_session):
    """A client-supplied org_id that doesn't exist at all must not silently
    grant access to anything — it must fail the same way a real-but-foreign
    org does, not leak information about which org IDs are valid."""
    org_service = OrganizationService()
    user_a = uuid.uuid4()
    await org_service.create(sqlite_session, user_a, OrgCreate(name="Org A", slug="org-a"))
    await sqlite_session.commit()

    token = make_token(user_a)
    forged_org_id = uuid.uuid4()

    with pytest.raises(ForbiddenError):
        await get_current_user(
            credentials=FakeCredentials(token),
            x_organization_id=str(forged_org_id),
            db=sqlite_session,
        )


@pytest.mark.asyncio
async def test_get_current_user_accepts_genuine_membership(sqlite_session):
    org_service = OrganizationService()
    user_a = uuid.uuid4()
    org_a = await org_service.create(sqlite_session, user_a, OrgCreate(name="Org A", slug="org-a"))
    await sqlite_session.commit()

    token = make_token(user_a)
    current_user = await get_current_user(
        credentials=FakeCredentials(token),
        x_organization_id=str(org_a.id),
        db=sqlite_session,
    )
    assert current_user.organization_id == org_a.id
    assert current_user.role.value == "owner"


@pytest.mark.asyncio
async def test_knowledge_base_from_org_a_not_visible_to_org_b(sqlite_session):
    """Real query-level isolation test: org B legitimately exists and is a
    real tenant, but must not be able to fetch org A's knowledge base by ID."""
    org_service = OrganizationService()
    kb_service = KnowledgeBaseService()

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    org_a = await org_service.create(sqlite_session, user_a, OrgCreate(name="Org A", slug="org-a"))
    org_b = await org_service.create(sqlite_session, user_b, OrgCreate(name="Org B", slug="org-b"))
    await sqlite_session.flush()

    kb = await kb_service.create(sqlite_session, org_a.id, KBCreate(name="Secret KB"))
    await sqlite_session.commit()

    # Org A can see its own KB
    fetched = await kb_service.get(sqlite_session, org_a.id, kb.id)
    assert fetched.id == kb.id

    # Org B cannot — even though it's asking for a real KB ID that exists
    with pytest.raises(NotFoundError):
        await kb_service.get(sqlite_session, org_b.id, kb.id)


@pytest.mark.asyncio
async def test_knowledge_base_list_never_leaks_other_orgs(sqlite_session):
    org_service = OrganizationService()
    kb_service = KnowledgeBaseService()

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    org_a = await org_service.create(sqlite_session, user_a, OrgCreate(name="Org A", slug="org-a"))
    org_b = await org_service.create(sqlite_session, user_b, OrgCreate(name="Org B", slug="org-b"))
    await sqlite_session.flush()

    await kb_service.create(sqlite_session, org_a.id, KBCreate(name="A's KB 1"))
    await kb_service.create(sqlite_session, org_a.id, KBCreate(name="A's KB 2"))
    await kb_service.create(sqlite_session, org_b.id, KBCreate(name="B's KB"))
    await sqlite_session.commit()

    org_a_kbs = await kb_service.list(sqlite_session, org_a.id)
    org_b_kbs = await kb_service.list(sqlite_session, org_b.id)

    assert len(org_a_kbs) == 2
    assert len(org_b_kbs) == 1
    assert all(kb.organization_id == org_a.id for kb in org_a_kbs)
    assert all(kb.organization_id == org_b.id for kb in org_b_kbs)


@pytest.mark.asyncio
async def test_org_membership_uniqueness_prevents_duplicate_role_confusion(sqlite_session):
    """A user cannot be added twice to the same org (which could otherwise
    create ambiguous-role scenarios for authorization checks)."""
    from app.core.exceptions import ValidationError
    from app.domains.organizations.schemas import OrgMemberCreate
    from app.models.organization_member import OrgRole

    org_service = OrganizationService()
    owner_id = uuid.uuid4()
    member_id = uuid.uuid4()
    org = await org_service.create(sqlite_session, owner_id, OrgCreate(name="Org", slug="org"))
    await sqlite_session.flush()

    await org_service.add_member(
        sqlite_session, org.id, OrgMemberCreate(user_id=member_id, role=OrgRole.viewer)
    )
    await sqlite_session.flush()

    with pytest.raises(ValidationError):
        await org_service.add_member(
            sqlite_session, org.id, OrgMemberCreate(user_id=member_id, role=OrgRole.admin)
        )
