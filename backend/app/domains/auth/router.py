import uuid

import structlog
from fastapi import APIRouter, Depends
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.domains.auth.dependencies import get_current_user
from app.domains.auth.schemas import AuthMeResponse, CurrentUser, TokenVerifyRequest
from app.models.organization_member import OrganizationMember

router = APIRouter()
logger = structlog.get_logger()


@router.post("/verify")
async def verify_token(
    body: TokenVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Validate a Supabase access token and return user info."""
    try:
        payload = jwt.decode(
            body.access_token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
    except JWTError as e:
        raise UnauthorizedError(f"Invalid token: {e}")

    user_id_str = payload.get("sub")
    email = payload.get("email", "")
    if not user_id_str:
        raise UnauthorizedError("Token missing subject claim")

    user_id = uuid.UUID(user_id_str)

    # Return memberships
    stmt = select(OrganizationMember).where(OrganizationMember.user_id == user_id)
    result = await db.execute(stmt)
    members = result.scalars().all()

    return {
        "id": str(user_id),
        "email": email,
        "organizations": [
            {"id": str(m.organization_id), "role": m.role.value} for m in members
        ],
    }


@router.get("/me", response_model=AuthMeResponse)
async def get_me(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's profile and organization memberships."""
    stmt = select(OrganizationMember).where(
        OrganizationMember.user_id == current_user.id
    )
    result = await db.execute(stmt)
    members = result.scalars().all()

    return AuthMeResponse(
        id=current_user.id,
        email=current_user.email,
        organizations=[
            {"id": str(m.organization_id), "role": m.role.value} for m in members
        ],
    )
