import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from fastapi import status, HTTPException

from app.core.settings import settings
from app.models.auth import User
from app.schemas.system import DiagnosticCheck, ServiceStatus
from app.services.health_checks import collect_preflight_checks
from app.services.host_control import HostControlError, request_helper
from app.services.sender_health import read_sender_health
from app.services.config_snapshots import target_lock, bundle_for, read_selected
from app.core.db import get_engine
from app.models.site_config import ConfigSnapshot
from sqlmodel import Session


@dataclass
class ServiceCommandFailure(Exception):
    status_code: int
    payload: ServiceStatus


@dataclass
class CommandContext:
    command: list[str] | None = None
    exit_code: int | None = None
    stderr_tail: str | None = None


def _command_text(command: list[str] | None) -> str | None:
    if not command:
        return None
    return " ".join(command)


def _tail_output(stdout: str | None, stderr: str | None) -> str | None:
    if stdout is None and stderr is None:
        return None
    combined = "\n".join(part for part in [(stderr or "").strip(), (stdout or "").strip()] if part)
    if not combined:
        return None
    return "\n".join(combined.splitlines()[-10:])


def _blocking_failures(checks: list[DiagnosticCheck]) -> list[str]:
    return [f"{check.name}: {check.detail}" for check in checks if check.blocking and not check.ok]


def _allowed_actions_for_status(service_state: str, preflight_ok: bool) -> list[str]:
    if service_state == "active":
        actions = ["stop"]
        if preflight_ok:
            actions.append("restart")
        return actions
    if service_state in {"activating", "deactivating"}:
        return ["stop"]
    if service_state in {"inactive", "failed"}:
        return ["start"] if preflight_ok else []
    return []


def _service_status_from_result(
    service_state: str,
    detail: str,
    *,
    checks: list[DiagnosticCheck],
    context: CommandContext | None = None,
) -> ServiceStatus:
    failures = _blocking_failures(checks)
    preflight_ok = not failures
    return ServiceStatus(
        service_name=settings.sender_service_name,
        running=service_state == "active",
        status=service_state,
        detail=detail,
        allowed_actions=_allowed_actions_for_status(service_state, preflight_ok),
        preflight_ok=preflight_ok,
        preflight_failures=failures,
        last_command=_command_text(context.command) if context else None,
        last_exit_code=context.exit_code if context else None,
        stderr_tail=context.stderr_tail if context else None,
    )


def _read_service_state(user: User | None) -> tuple[str, str, dict]:
    try:
        result = request_helper("sender_status", actor=user)
    except HostControlError as exc:
        return "unavailable", f"platform={sys.platform}; env={Path(settings.sender_env_path).resolve()}; service={settings.sender_service_name}; helper_error={exc.message}", {}

    service_state = result.get("service_state") or "unknown"
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    detail = f"platform={sys.platform}; env={Path(settings.sender_env_path).resolve()}; service={settings.sender_service_name}"
    if stderr:
        detail = f"{detail}; state_error={stderr}"
    elif stdout and stdout != service_state:
        detail = f"{detail}; state_output={stdout}"
    return service_state, detail, result


def _snapshot_status(user: User | None = None, *, context: CommandContext | None = None) -> ServiceStatus:
    try:
        checks = collect_preflight_checks()
    except (OSError, ValueError, HTTPException):
        checks = [DiagnosticCheck(name="selected-config", ok=False, detail="Selected configuration is unavailable",
                                  category="runtime", blocking=True, severity="critical")]
    service_state, detail, result = _read_service_state(user)
    snapshot = _service_status_from_result(service_state, detail, checks=checks, context=context)
    snapshot.media = read_sender_health(service_state, result)
    try:
        selected_bundle = read_selected()
    except (OSError, ValueError, HTTPException):
        selected_bundle = None
    selected = selected_bundle.selected if selected_bundle else None
    snapshot.selected = selected
    if snapshot.media.snapshot_id and service_state in {"active", "activating"}:
        with Session(get_engine()) as session:
            record = session.get(ConfigSnapshot, snapshot.media.snapshot_id)
            if record:
                snapshot.running_config = bundle_for(record)
        if selected and snapshot.running_config:
            snapshot.pending_configuration = selected.id != snapshot.media.snapshot_id
    elif service_state == "inactive":
        snapshot.pending_configuration = False
    snapshot.media.pending_config = snapshot.pending_configuration is True
    return snapshot


def get_service_status(user: User | None = None) -> ServiceStatus:
    with ExitStack() as stack:
        try:
            stack.enter_context(target_lock())
        except OSError:
            pass
        return _snapshot_status(user)


def _raise_action_failure(status_code: int, snapshot: ServiceStatus) -> None:
    raise ServiceCommandFailure(status_code=status_code, payload=snapshot)


def _validate_transition(action: str, snapshot: ServiceStatus) -> None:
    if action in {"start", "restart"} and not snapshot.preflight_ok:
        _raise_action_failure(status.HTTP_424_FAILED_DEPENDENCY, snapshot)
    if action == "start" and snapshot.status not in {"inactive", "failed"}:
        _raise_action_failure(status.HTTP_409_CONFLICT, snapshot)
    if action == "stop" and snapshot.status not in {"active", "activating", "deactivating"}:
        _raise_action_failure(status.HTTP_409_CONFLICT, snapshot)
    if action == "restart" and snapshot.status != "active":
        _raise_action_failure(status.HTTP_409_CONFLICT, snapshot)


def perform_service_action(action: str, user: User | None = None, *, expected_selection_id: str | None = None) -> ServiceStatus:
    # Stop never depends on publishing or validating a configuration. The helper
    # also serializes service commands if the data filesystem is unavailable.
    if action == "stop":
        with ExitStack() as stack:
            try:
                stack.enter_context(target_lock())
            except OSError:
                pass
            return _perform_service_action(action, user, None)
    with target_lock():
        selected_bundle = read_selected()
        selected = selected_bundle.selected if selected_bundle else None
        if expected_selection_id is None:
            raise HTTPException(428, "Review and provide the selected configuration before Start/Restart")
        if selected is None or selected.id != expected_selection_id:
            raise HTTPException(409, "Selected configuration changed; review it again before Start/Restart")
        return _perform_service_action(action, user, expected_selection_id)


def _perform_service_action(action: str, user: User | None, expected_selection_id: str | None) -> ServiceStatus:
    snapshot = _snapshot_status(user)
    _validate_transition(action, snapshot)
    helper_action = {"start": "sender_start", "stop": "sender_stop", "restart": "sender_restart"}[action]
    try:
        result = request_helper(helper_action, actor=user, payload={"expected_snapshot_id": expected_selection_id})
    except HostControlError as exc:
        details = exc.details or {}
        context = CommandContext(
            command=[helper_action],
            exit_code=details.get("exit_code"),
            stderr_tail=_tail_output(details.get("stdout"), details.get("stderr")) or exc.message,
        )
        failed_snapshot = _snapshot_status(user, context=context)
        _raise_action_failure(status.HTTP_502_BAD_GATEWAY, failed_snapshot)

    action_context = CommandContext(
        command=[str(result.get("command") or helper_action)],
        exit_code=result.get("exit_code"),
        stderr_tail=_tail_output(str(result.get("stdout") or ""), str(result.get("stderr") or "")),
    )
    return _snapshot_status(user, context=action_context)


def get_recent_logs(user: User | None = None) -> list[str]:
    try:
        result = request_helper("sender_logs", actor=user, payload={"lines": 50})
    except HostControlError as exc:
        return [f"Local control helper unavailable: {exc.message}"]
    lines = result.get("lines")
    if isinstance(lines, list) and lines:
        return [str(line) for line in lines]
    return ["No logs available yet"]
