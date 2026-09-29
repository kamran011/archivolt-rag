import uuid

from pydantic import BaseModel, EmailStr

from app.models.organization_member import OrgRole


class TokenPayload(BaseModel):
    sub: str
    email: str
    exp: int
    aud: str | list[str] | None = None


class CurrentUser(BaseModel):
    id: uuid.UUID
    email: str
    organization_id: uuid.UUID | None = None
    role: OrgRole | None = None


class AuthMeResponse(BaseModel):
    id: uuid.UUID
    email: str
    organizations: list[dict]


class TokenVerifyRequest(BaseModel):
    access_token: str
