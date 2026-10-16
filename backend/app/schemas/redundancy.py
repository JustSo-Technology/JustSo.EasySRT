from typing import Literal

from pydantic import BaseModel, Field


RedundancyMode = Literal["single_node", "partner_redundancy"]
RedundancyProductState = Literal["protected", "degraded_protection", "failed_over", "unprotected", "transitioning"]
RedundancyOutputState = Literal["healthy", "degraded", "no_verified_output", "verification_unavailable", "unknown"]
RedundancySyncState = Literal["up_to_date", "syncing", "behind", "sync_failed", "read_only", "not_applicable", "unknown"]
RedundancyNodeRole = Literal["live", "standby", "partner", "unknown"]
RedundancyConnectionState = Literal["online", "offline", "unknown"]
RedundancyRuntimeState = Literal["healthy", "valid", "degraded", "invalid", "unknown"]


class RedundancyNodeSummary(BaseModel):
    id: str
    label: str
    role: RedundancyNodeRole = "unknown"
    connection_state: RedundancyConnectionState = "unknown"
    stream_authority: bool = False
    config_authority: bool = False
    runtime_status: RedundancyRuntimeState = "unknown"
    sync_status: RedundancySyncState = "unknown"
    takeover_ready: bool = False
    detail: str | None = None


class RedundancyStatus(BaseModel):
    mode: RedundancyMode = "single_node"
    product_state: RedundancyProductState = "unprotected"
    product_state_reason: str = "Partner redundancy is not enabled on this node."
    live_node_id: str | None = None
    live_node_label: str | None = None
    standby_node_id: str | None = None
    standby_node_label: str | None = None
    output_status: RedundancyOutputState = "verification_unavailable"
    output_status_reason: str = "Output verification is not configured."
    config_sync_status: RedundancySyncState = "not_applicable"
    config_sync_reason: str = "Partner redundancy is not enabled."
    partner_takeover_ready: bool = False
    automatic_takeover_paused: bool = False
    allowed_actions: list[str] = Field(default_factory=list)
    last_action: str = "No partner node configured."
    source: Literal["default", "state_file"] = "default"
    nodes: list[RedundancyNodeSummary] = Field(default_factory=list)
