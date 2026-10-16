from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReplicatedConfigState(SQLModel, table=True):
    id: str = Field(default="default", primary_key=True)
    authority_node_id: str
    authority_node_label: str
    current_version: int = 1
    last_change_summary: str = "Initialized from local config"
    last_changed_by_user_id: str | None = Field(default=None, foreign_key="user.id")
    last_changed_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ReplicatedConfigVersionRecord(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    version: int = Field(index=True, unique=True)
    app_payload: str
    site_payload: str
    changed_by_user_id: str | None = Field(default=None, foreign_key="user.id")
    change_summary: str
    origin_node_id: str
    origin_node_label: str
    created_at: datetime = Field(default_factory=utcnow)


class PartnerSyncState(SQLModel, table=True):
    id: str = Field(default="partner", primary_key=True)
    partner_node_id: str | None = None
    partner_node_label: str | None = None
    last_acked_version: int | None = None
    sync_state: str = "not_configured"
    runtime_validation_state: str = "unknown"
    takeover_eligibility: str = "unknown"
    last_sync_attempt_at: datetime | None = None
    last_sync_success_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
