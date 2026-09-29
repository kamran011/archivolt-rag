import uuid

import structlog
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.domains.auth.schemas import CurrentUser
from app.models.organization_member import OrganizationMember, OrgRole

logger = structlog.get_logger()

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if not credentials:
        raise UnauthorizedError("Missing authorization token")

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience="authenticated",
            options={"verify_aud": False},
        )
    except JWTError as e:
        logger.warning("jwt_validation_failed", error=str(e))
        raise UnauthorizedError("Invalid or expired token") from e

    user_id_str = payload.get("sub")
    email = payload.get("email", "")
    if not user_id_str:
        raise UnauthorizedError("Token missing subject claim")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedError("Invalid user ID in token") from None

    if not x_organization_id:
        return CurrentUser(id=user_id, email=email)

    try:
        org_id = uuid.UUID(x_organization_id)
    except ValueError:
        raise UnauthorizedError("Invalid organization ID header") from None

    # Look up membership — this is the ONLY way org_id is resolved
    stmt = select(OrganizationMember).where(
        OrganizationMember.user_id == user_id,
        OrganizationMember.organization_id == org_id,
    )
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()

    if not member:
        raise ForbiddenError("Not a member of this organization")

    return CurrentUser(
        id=user_id,
        email=email,
        organization_id=org_id,
        role=member.role,
    )


def require_role(*roles: OrgRole):
    """Dependency factory — checks that the current user has one of the required roles."""

    async def check(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in roles:
            raise ForbiddenError(
                f"Requires role: {', '.join(r.value for r in roles)}"
            )
        return current_user

    return check


def require_org(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that ensures an org context is present (X-Organization-Id header was provided)."""
    if not current_user.organization_id:
        raise UnauthorizedError("X-Organization-Id header is required")
    return current_user
