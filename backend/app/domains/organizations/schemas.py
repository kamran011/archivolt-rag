import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.organization_member import OrgRole


class OrgCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9-]+$", v):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
        if len(v) < 2 or len(v) > 100:
            raise ValueError("Slug must be 2-100 characters")
        return v

    @field_validator("name")
    @classmethod
    def name_length(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v.strip()


class OrgUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    settings: dict
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    role: OrgRole | None = None

    model_config = {"from_attributes": True}


class OrgMemberCreate(BaseModel):
    email: str
    role: OrgRole = OrgRole.member


class OrgMemberUpdate(BaseModel):
    role: OrgRole


class OrgMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: OrgRole
    created_at: datetime

    model_config = {"from_attributes": True}
