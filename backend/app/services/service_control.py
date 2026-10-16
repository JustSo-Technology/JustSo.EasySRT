import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import status

from app.core.settings import settings
from app.models.auth import User
from app.schemas.system import DiagnosticCheck, ServiceStatus
from app.services.health_checks import collect_preflight_checks
from app.services.host_control import HostControlError, request_helper


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
    if service_state == "activating":
        return ["stop"]
    if service_state in {"inactive", "failed", "deactivating", "unknown", "unavailable"}:
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


def _read_service_state(user: User | None) -> tuple[str, str]:
    try:
        result = request_helper("sender_status", actor=user)
    except HostControlError as exc:
        return "unavailable", f"platform={sys.platform}; env={Path(settings.sender_env_path).resolve()}; service={settings.sender_service_name}; helper_error={exc.message}"

    service_state = result.get("service_state") or "unknown"
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    detail = f"platform={sys.platform}; env={Path(settings.sender_env_path).resolve()}; service={settings.sender_service_name}"
    if stderr:
        detail = f"{detail}; state_error={stderr}"
    elif stdout and stdout != service_state:
        detail = f"{detail}; state_output={stdout}"
    return service_state, detail


def _snapshot_status(user: User | None = None, *, context: CommandContext | None = None) -> ServiceStatus:
    checks = collect_preflight_checks()
    service_state, detail = _read_service_state(user)
    return _service_status_from_result(service_state, detail, checks=checks, context=context)


def get_service_status(user: User | None = None) -> ServiceStatus:
    return _snapshot_status(user)


def _raise_action_failure(status_code: int, snapshot: ServiceStatus) -> None:
    raise ServiceCommandFailure(status_code=status_code, payload=snapshot)


def _validate_transition(action: str, snapshot: ServiceStatus) -> None:
    if action == "start" and snapshot.status == "active":
        _raise_action_failure(status.HTTP_409_CONFLICT, snapshot)
    if action == "stop" and snapshot.status not in {"active", "activating"}:
        _raise_action_failure(status.HTTP_409_CONFLICT, snapshot)
    if action == "restart" and snapshot.status != "active":
        _raise_action_failure(status.HTTP_409_CONFLICT, snapshot)
    if action in {"start", "restart"} and not snapshot.preflight_ok:
        _raise_action_failure(status.HTTP_424_FAILED_DEPENDENCY, snapshot)


def perform_service_action(action: str, user: User | None = None) -> ServiceStatus:
    snapshot = _snapshot_status(user)
    _validate_transition(action, snapshot)
    helper_action = {"start": "sender_start", "stop": "sender_stop", "restart": "sender_restart"}[action]
    try:
        result = request_helper(helper_action, actor=user)
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
