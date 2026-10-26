from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.services.api_scopes import ScopeGrant


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TokenCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    integration: str = Field(min_length=1, max_length=120)
    owner_id: str
    grants: list[ScopeGrant] = Field(min_length=1, max_length=256)
    expires_at: datetime
    preset: str = 'custom'
    current_password: str = Field(min_length=1, max_length=1024, repr=False, exclude=True)


class TokenPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    grants: list[ScopeGrant] | None = Field(default=None, min_length=1, max_length=256)
    expires_at: datetime | None = None
    current_password: str | None = Field(default=None, max_length=1024, repr=False, exclude=True)


class TokenRotate(StrictModel):
    expected_revision: int = Field(ge=1)
    overlap_seconds: int = Field(default=0, ge=0, le=86400)
    current_password: str = Field(min_length=1, max_length=1024, repr=False, exclude=True)


class BulkRevoke(StrictModel):
    ids: list[str] = Field(min_length=1, max_length=100)
