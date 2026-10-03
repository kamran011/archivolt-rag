import uuid

import structlog
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.jwks import JWKSUnavailableError, jwks_cache
from app.domains.auth.schemas import CurrentUser
from app.models.organization_member import OrganizationMember, OrgRole

logger = structlog.get_logger()

security = HTTPBearer(auto_error=False)


ASYMMETRIC_ALGORITHMS = {"ES256", "RS256"}


async def _verification_key_and_alg(token: str) -> tuple[str | dict, str]:
    """Chooses the verification key from the token header's alg. The alg is
    only ever used to *select among our own allowed key types* — HS256 is
    verified solely against the configured secret and asymmetric algs solely
    against the issuer's published keys, so a forged header can't downgrade
    verification (e.g. HMAC-signing with a public key)."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise UnauthorizedError("Invalid or expired token") from e

    alg = header.get("alg")
    if alg == "HS256":
        if not settings.JWT_SECRET:
            raise UnauthorizedError("Invalid or expired token")
        return settings.JWT_SECRET, alg
    if alg in ASYMMETRIC_ALGORITHMS:
        try:
            jwk = await jwks_cache.get_key(header.get("kid"))
        except JWKSUnavailableError as e:
            # Fail closed: never accept a token we cannot verify.
            logger.error("jwks_unavailable", error=str(e))
            raise UnauthorizedError("Unable to verify token") from e
        if jwk is None or jwk.get("alg", alg) != alg:
            raise UnauthorizedError("Invalid or expired token")
        return jwk, alg
    raise UnauthorizedError("Invalid or expired token")


async def decode_access_token(token: str) -> tuple[uuid.UUID, str]:
    """Validate a Supabase access token (signature, expiry, audience) and return
    (user_id, email). Single place tokens are verified."""
    key, alg = await _verification_key_and_alg(token)
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=settings.JWT_AUDIENCE,
            # jose skips the audience check when the claim is absent unless required.
            options={"require_aud": True},
        )
    except JWTError as e:
        logger.warning("jwt_validation_failed", error=str(e))
        raise UnauthorizedError("Invalid or expired token") from e

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedError("Token missing subject claim")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise UnauthorizedError("Invalid user ID in token") from None
    return user_id, payload.get("email", "")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> CurrentUser:
    if not credentials:
        raise UnauthorizedError("Missing authorization token")

    user_id, email = await decode_access_token(credentials.credentials)

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


def require_role_in_path_org(*roles: OrgRole):
    """Like require_role, for routes that also carry an org id in the URL. The caller's role
    comes from their membership in the X-Organization-Id org; without this check an admin of
    org A could act on org B by naming B in the path. A mismatch is reported as 404 so
    other orgs' ids can't be probed."""

    async def check(
        org_id: uuid.UUID,
        current_user: CurrentUser = Depends(require_role(*roles)),
    ) -> CurrentUser:
        if current_user.organization_id != org_id:
            raise NotFoundError("Organization not found")
        return current_user

    return check


def require_org(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Dependency that ensures an org context is present (X-Organization-Id header was provided)."""
    if not current_user.organization_id:
        raise UnauthorizedError("X-Organization-Id header is required")
    return current_user
