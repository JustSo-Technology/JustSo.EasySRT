"""Incoming bearer credentials are hashes; never portable configuration data."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlmodel import Field, SQLModel


def now():
    return datetime.now(timezone.utc)


class ApiIdentity(SQLModel, table=True):
    id: str = Field(default='local', primary_key=True)
    instance_id: str = Field(default_factory=lambda: str(uuid4()))


class ApiToken(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    instance_id: str
    name: str
    integration: str
    owner_id: str = Field(index=True, foreign_key='user.id')
    creator_id: str
    grants_json: str
    preset: str = 'custom'
    preset_version: int = 1
    preset_customized: bool = False
    revision: int = 1
    created_at: datetime = Field(default_factory=now)
    expires_at: datetime
    revoked_at: datetime | None = None


class ApiCredential(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    token_id: str = Field(index=True, foreign_key='apitoken.id')
    secret_hash: str
    created_at: datetime = Field(default_factory=now)
    last_used_at: datetime | None = None
    retire_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiAudit(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    token_id: str | None = Field(default=None, index=True)
    actor_id: str
    action: str
    resource_id: str = ''
    outcome: str = 'success'
    request_id: str = ''
    detail_json: str = '{}'
    created_at: datetime = Field(default_factory=now, index=True)


class ApiCommand(SQLModel, table=True):
    id: str = Field(primary_key=True)
    token_id: str = Field(index=True)
    request_hash: str
    status: str = 'pending'
    result_json: str | None = None
    created_at: datetime = Field(default_factory=now, index=True)
