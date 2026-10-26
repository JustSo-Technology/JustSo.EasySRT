"""Read-only projection of supervisor evidence; never starts a service."""
import json
import time

from pydantic import ValidationError

from app.core.settings import settings
from app.schemas.system import SenderHealth


def _load_snapshot() -> SenderHealth:
    raw = settings.sender_env_path.with_name("sender_status.json").read_bytes()
    if len(raw) > 65536:
        raise ValueError("Oversized status")
    payload = json.loads(raw)
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported status")
    return SenderHealth.model_validate(payload)


def read_sender_health(service_state: str, helper_result: dict) -> SenderHealth:
    if service_state == "inactive":
        try:
            previous = _load_snapshot()
            if previous.state == "stopped":
                return previous
        except (OSError, ValueError, TypeError, AttributeError, ValidationError):
            pass
        return SenderHealth(state="stopped", reason="service_inactive", detail="Sender service is stopped.")
    if service_state in {"failed", "deactivating"}:
        return SenderHealth(state="stopped" if service_state == "inactive" else "degraded",
                            reason=f"service_{service_state}", detail=f"Sender service is {service_state}.")
    if service_state not in {"active", "activating"}:
        return SenderHealth(reason="service_unavailable", detail="Sender service status is unavailable.")
    try:
        health = _load_snapshot()
        age = time.monotonic() - health.heartbeat_monotonic
        if not 0 <= age <= 3.5:
            raise ValueError("Stale status")
        if not health.supervisor_pid or health.supervisor_pid != helper_result.get("main_pid"):
            raise ValueError("Different sender process")
        if helper_result.get("invocation_id") != health.invocation_id:
            raise ValueError("Different service invocation")
        # Account for time between publication and this API read. A fresh
        # heartbeat must not conceal old media samples near their deadlines.
        for counter in (health.input, health.output):
            if counter.age_seconds is not None:
                counter.age_seconds += age
        if health.state == "healthy" and (
            health.input.age_seconds is None or health.output.age_seconds is None
            or health.input.age_seconds >= health.policy.get("input_stall_seconds", 15)
            or health.output.age_seconds >= health.policy.get("output_stall_seconds", 15)
        ):
            health.state = "degraded"
            health.reason = "media_stalled"
            health.detail = "Required media progress is stale; waiting for the supervisor's recovery update."
        return health
    except (OSError, ValueError, TypeError, AttributeError, ValidationError):
        return SenderHealth(reason="supervision_unavailable",
                            detail="Media health is unavailable or stale. Restart to activate recovery, or inspect sender logs.")
