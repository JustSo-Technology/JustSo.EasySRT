from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SavedSiteConfigRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True, unique=True)
    site_payload: str
    revision: int = Field(default=1)
    created_by_user_id: str | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_loaded_at: datetime | None = None


class SavedInputRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True, unique=True)
    input_payload: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SavedDestinationRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(index=True, unique=True)
    destination_payload: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SiteConfigState(SQLModel, table=True):
    id: str = Field(default="default", primary_key=True)
    active_saved_config_id: str | None = Field(default=None, foreign_key="savedsiteconfigrecord.id")
    updated_at: datetime = Field(default_factory=utcnow)


class ConfigSnapshot(SQLModel, table=True):
    """Copied values, deliberately independent of the mutable preset library."""
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    bundle_payload: str
    digest: str
    source_preset_id: str | None = None
    source_revision: int | None = None
    source_name: str = "Legacy configuration"
    target: str = "default"
    actor_id: str | None = None
    request_id: str | None = Field(default=None, unique=True)
    request_digest: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SelectedConfigState(SQLModel, table=True):
    id: str = Field(default="default", primary_key=True)
    snapshot_id: str
