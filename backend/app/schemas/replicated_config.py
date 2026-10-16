from datetime import datetime
from typing import Literal

from pydantic import BaseModel


PartnerSyncStateValue = Literal["not_configured", "awaiting_ack", "up_to_date", "behind", "sync_failed"]
RuntimeValidationStateValue = Literal["valid", "invalid", "unknown"]
TakeoverEligibilityValue = Literal["eligible", "ineligible_config_behind", "ineligible_runtime_invalid", "unknown"]


class ReplicatedConfigStatus(BaseModel):
    authority_node_id: str
    authority_node_label: str
    current_version: int
    last_change_summary: str
    last_changed_at: datetime
    last_changed_by_user_id: str | None = None
    partner_node_id: str | None = None
    partner_node_label: str | None = None
    last_acked_version: int | None = None
    partner_sync_state: PartnerSyncStateValue
    runtime_validation_state: RuntimeValidationStateValue
    takeover_eligibility: TakeoverEligibilityValue
    last_sync_attempt_at: datetime | None = None
    last_sync_success_at: datetime | None = None
    last_error: str | None = None


class PartnerAckRequest(BaseModel):
    partner_node_id: str
    partner_node_label: str
    acked_version: int
    runtime_validation_state: RuntimeValidationStateValue = "valid"
    error: str | None = None
