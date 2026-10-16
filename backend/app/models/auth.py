from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    OWNER = "owner"
    ENGINEER = "engineer"
    OPERATOR = "operator"


class User(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: UserRole = Field(default=UserRole.OWNER)
    disabled: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None


class SessionRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    last_seen_at: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None
