import json
import platform

from app.core.settings import settings
from app.schemas.redundancy import RedundancyNodeSummary, RedundancyStatus


def _default_redundancy_status() -> RedundancyStatus:
    hostname = platform.node() or "local-node"
    return RedundancyStatus(
        live_node_id=hostname,
        live_node_label=hostname,
        nodes=[
            RedundancyNodeSummary(
                id=hostname,
                label=hostname,
                role="live",
                connection_state="online",
                stream_authority=True,
                config_authority=True,
                runtime_status="unknown",
                sync_status="not_applicable",
                takeover_ready=False,
                detail="Single-node operation. Partner redundancy has not been configured yet.",
            )
        ],
    )


def get_redundancy_status() -> RedundancyStatus:
    path = settings.redundancy_state_path
    if not path.exists():
        return _default_redundancy_status()

    payload = json.loads(path.read_text())
    status = RedundancyStatus.model_validate(payload)
    if not status.nodes and status.live_node_id:
        status.nodes = [
            RedundancyNodeSummary(
                id=status.live_node_id,
                label=status.live_node_label or status.live_node_id,
                role="live",
                connection_state="unknown",
                stream_authority=True,
                config_authority=status.mode == "single_node",
                runtime_status="unknown",
                sync_status=status.config_sync_status,
                takeover_ready=status.partner_takeover_ready,
            )
        ]
    status.source = "state_file"
    return status
