#!/usr/bin/env python3
from __future__ import annotations

import json
import fcntl
import logging
import os
import pwd
import signal
import stat
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


SOCKET_PATH = Path(os.environ.get("EASYSRT_HELPER_SOCKET_PATH", "/run/justso-easysrt/helper.sock"))
APP_USER = os.environ.get("EASYSRT_APP_USER", "easysrt")
SENDER_SERVICE = os.environ.get("EASYSRT_SENDER_SERVICE", "easysrt-sender")
UPDATE_SCRIPT = Path(os.environ.get("EASYSRT_UPDATE_SCRIPT", "/usr/local/lib/justso-easysrt/update-ubuntu.sh"))
APP_ROOT = Path(os.environ.get("EASYSRT_APP_ROOT", "/opt/justso-easysrt"))
POLICY_PATH = Path("/etc/justso-easysrt/update-policy.json")
UPDATE_STATE_PATH = Path("/var/lib/justso-easysrt-updates/update-job.json")
UPDATE_LOG_PATH = Path("/var/lib/justso-easysrt-updates/update-job.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
LOGGER = logging.getLogger("easysrt-host-control-helper")
STOP_EVENT = threading.Event()


class HelperRequestError(Exception):
    def __init__(self, error_code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}


def _allowed_uid_gid() -> tuple[int, int]:
    record = pwd.getpwnam(APP_USER)
    return record.pw_uid, record.pw_gid


def _ensure_socket_permissions() -> None:
    _, gid = _allowed_uid_gid()
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.chown(SOCKET_PATH.parent, 0, gid)
    os.chmod(SOCKET_PATH.parent, 0o750)
    os.chown(SOCKET_PATH, 0, gid)
    os.chmod(SOCKET_PATH, 0o660)


def _peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    creds = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", creds)
    return pid, uid, gid


def _validate_peer(connection: socket.socket) -> None:
    allowed_uid, _ = _allowed_uid_gid()
    _, uid, _ = _peer_credentials(connection)
    if uid not in {0, allowed_uid}:
        raise HelperRequestError("forbidden", "Client is not permitted to use the local control helper")


def _run_command(command: list[str], *, timeout: float = 5, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout, cwd="/", pass_fds=pass_fds)
    except subprocess.TimeoutExpired as exc:
        raise HelperRequestError("command_timeout", "Host control command timed out; refresh service status before retrying") from exc


def _tail_text(stdout: str, stderr: str) -> str | None:
    combined = "\n".join(part for part in [stderr.strip(), stdout.strip()] if part)
    if not combined:
        return None
    return "\n".join(combined.splitlines()[-10:])


def _actor_label(actor: dict[str, Any]) -> str:
    username = actor.get("username") or "unknown"
    role = actor.get("role") or "unknown"
    return f"{username} ({role}) api_token={str(actor.get('api_token_id') or 'session')[:36]}"


def _sender_status() -> dict[str, Any]:
    result = _run_command(["/usr/bin/systemctl", "show", SENDER_SERVICE,
                           "--property=ActiveState", "--property=MainPID", "--property=InvocationID"])
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    properties = dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)
    state = properties.get("ActiveState") or ("unavailable" if stderr else "unknown")
    return {
        "service_state": state,
        "main_pid": int(properties.get("MainPID") or 0),
        "invocation_id": properties.get("InvocationID") or "",
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": result.returncode,
    }


def _sender_logs(payload: dict[str, Any]) -> dict[str, Any]:
    limit = int(payload.get("lines", 50))
    limit = min(max(limit, 1), 200)
    result = _run_command(["/usr/bin/journalctl", "-u", SENDER_SERVICE, "-n", str(limit), "--no-pager"])
    return {
        "lines": result.stdout.strip().splitlines() if result.stdout.strip() else [],
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "exit_code": result.returncode,
    }


def _pin_sender_runtime(control_fd: int, expected_snapshot_id: str, *, validate_only: bool = False) -> None:
    # Read and publish application-owned files AS the service user, never root.
    # The fixed program copies data; no manifest content is executed by root.
    program = """
import fcntl, json, os, pathlib, sys, tempfile
os.umask(0o077)
source, target = map(pathlib.Path, sys.argv[1:3])
# Keep the SAME open-file-description lock through runuser, even if the
# helper is restarted while this child is publishing the applied manifest.
fcntl.flock(int(sys.argv[3]), fcntl.LOCK_EX | fcntl.LOCK_NB)
raw = source.read_bytes()
if len(raw) > 65536: raise ValueError('Runtime too large')
data = json.loads(raw)
if data.get('schema_version') != 1 or not data.get('ffmpeg_args'): raise ValueError('Apply configuration before starting')
if data.get('snapshot_id') != sys.argv[4]: raise ValueError('Selected configuration changed; review again')
if sys.argv[5] == 'validate': sys.exit(0)
with tempfile.NamedTemporaryFile('wb', dir=target.parent, delete=False) as handle:
    handle.write(raw)
    handle.flush()
    os.fsync(handle.fileno())
    temporary = pathlib.Path(handle.name)
try:
    temporary.replace(target)
    fd = os.open(target.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
finally:
    temporary.unlink(missing_ok=True)
"""
    data = APP_ROOT / "backend" / "data"
    result = _run_command(["/usr/sbin/runuser", "-u", APP_USER, "--", "/usr/bin/python3", "-I", "-c", program,
                           str(data / "selected/runtime_config.json"), str(data / "applied_sender.json"), str(control_fd), expected_snapshot_id, "validate" if validate_only else "publish"],
                          pass_fds=(control_fd,))
    if result.returncode:
        raise HelperRequestError("runtime_unavailable", "Unable to apply sender runtime; review and Apply configuration before starting")


def _service_action(systemctl_action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = (payload or {}).get("expected_snapshot_id")
    if systemctl_action in {"start", "restart"} and (not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9-]{36}", expected)):
        raise HelperRequestError("review_required", "Selected snapshot identity is required before Start/Restart")
    lock_path = SOCKET_PATH.parent / "sender-control.lock"
    with lock_path.open("a") as lock:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HelperRequestError("control_busy", "Another sender action is still completing; refresh status")
                time.sleep(.05)
        return _locked_service_action(systemctl_action, lock.fileno(), expected)


def _locked_service_action(systemctl_action: str, control_fd: int, expected_snapshot_id: str | None) -> dict[str, Any]:
    if systemctl_action in {"start", "restart"}:
        reload_result = _run_command(["/usr/bin/systemctl", "daemon-reload"])
        if reload_result.returncode != 0:
            raise HelperRequestError(
                "daemon_reload_failed",
                "systemctl daemon-reload failed",
                {
                    "command": "/usr/bin/systemctl daemon-reload",
                    "exit_code": reload_result.returncode,
                    "stdout": reload_result.stdout.strip(),
                    "stderr": reload_result.stderr.strip(),
                },
            )

    current = _sender_status()["service_state"]
    if systemctl_action == "start" and current not in {"inactive", "failed"}:
        raise HelperRequestError("invalid_transition", "Sender is already starting or running; refresh service status")
    if systemctl_action in {"start", "restart"}:
        _pin_sender_runtime(control_fd, expected_snapshot_id, validate_only=True)
    if systemctl_action == "restart":
        stopped = _run_command(["/usr/bin/systemctl", "stop", SENDER_SERVICE], timeout=25)
        if stopped.returncode:
            raise HelperRequestError("stop_failed", "Old sender could not be stopped; no replacement was started")
    if systemctl_action in {"start", "restart"}:
        _pin_sender_runtime(control_fd, expected_snapshot_id)
        _run_command(["/usr/bin/systemctl", "reset-failed", SENDER_SERVICE])
    command = ["/usr/bin/systemctl", "start" if systemctl_action == "restart" else systemctl_action, SENDER_SERVICE]
    result = _run_command(command, timeout=25)
    if result.returncode != 0:
        raise HelperRequestError(
            "service_action_failed",
            f"{systemctl_action} failed",
            {
                "command": " ".join(command),
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            },
        )
    return {
        "command": " ".join(command),
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _validate_root_path(path: Path, *, directory: bool = False) -> None:
    """Reject symlinks and any ancestor a service account could replace."""
    if not path.is_absolute() or ".." in path.parts:
        raise HelperRequestError("unsafe_update_path", "Update paths must be absolute and canonical")
    for current in [*reversed(path.parents), path]:
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise HelperRequestError("unsafe_update_path", f"Protected update path unavailable: {current}") from exc
        expected_directory = current != path or directory
        valid_type = stat.S_ISDIR(metadata.st_mode) if expected_directory else stat.S_ISREG(metadata.st_mode)
        if metadata.st_uid != 0 or metadata.st_mode & 0o022 or not valid_type:
            raise HelperRequestError("unsafe_update_path", f"Update path is not protected by root: {current}")
        if not expected_directory and metadata.st_nlink != 1:
            raise HelperRequestError("unsafe_update_path", "Protected update files cannot have hard links")


def _update_policy() -> dict[str, str]:
    _validate_root_path(POLICY_PATH)
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HelperRequestError("invalid_update_policy", "Cannot read host update policy") from exc
    if not isinstance(policy, dict):
        raise HelperRequestError("invalid_update_policy", "Host update policy must be an object")
    url, ref = policy.get("repo_url"), policy.get("repo_ref")
    if not isinstance(url, str) or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", url):
        raise HelperRequestError("invalid_update_policy", "Host update policy requires a GitHub HTTPS repository")
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref) or ".." in ref:
        raise HelperRequestError("invalid_update_policy", "Host update policy contains an invalid ref")
    return {"repo_url": url, "repo_ref": ref}


def _open_tracking_file(path: Path) -> int:
    # The app may update status contents, but cannot replace these directory
    # entries with symlinks or hard links to arbitrary root-writable files.
    _validate_root_path(path.parent, directory=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o660)
    try:
        metadata = os.fstat(descriptor)
        _, gid = _allowed_uid_gid()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_nlink != 1:
            raise HelperRequestError("unsafe_update_path", "Update tracking file is not a root-owned regular file")
        os.fchown(descriptor, 0, gid)
        os.fchmod(descriptor, 0o660)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _update_control_plane(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_root_path(UPDATE_SCRIPT)
    policy = _update_policy()
    for key, approved in policy.items():
        if payload.get(key) not in (None, "", approved):
            raise HelperRequestError("forbidden_update_source", "Update source must match the root-managed host policy")
    for key, approved in (("state_file", UPDATE_STATE_PATH), ("log_file", UPDATE_LOG_PATH)):
        if payload.get(key) not in (None, "", str(approved)):
            raise HelperRequestError("unsafe_update_path", "Update tracking paths are fixed by the host")
    token = payload.get("github_token")
    if token is not None and (not isinstance(token, str) or len(token) > 4096 or (token and not re.fullmatch(r"[A-Za-z0-9_]+", token))):
        raise HelperRequestError("invalid_request", "Invalid GitHub token")
    # Do not inherit Python, shell, Git, or PATH overrides from callers.
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root", "LANG": "C.UTF-8",
        "EASYSRT_REPO_URL": policy["repo_url"],
        "EASYSRT_REPO_REF": policy["repo_ref"],
        "EASYSRT_UPDATE_STATE_FILE": str(UPDATE_STATE_PATH),
        "EASYSRT_UPDATE_LOG_FILE": str(UPDATE_LOG_PATH),
    }
    if token:
        env["GITHUB_TOKEN"] = token
    os.close(_open_tracking_file(UPDATE_STATE_PATH))
    with os.fdopen(_open_tracking_file(UPDATE_LOG_PATH), "a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            ["/bin/bash", str(UPDATE_SCRIPT)],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
            cwd="/",
        )
    threading.Thread(target=process.wait, name=f"update-job-{process.pid}", daemon=True).start()
    return {"pid": process.pid}


def _dispatch(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action == "sender_status":
        return _sender_status()
    if action == "sender_logs":
        return _sender_logs(payload)
    if action == "sender_start":
        return _service_action("start", payload)
    if action == "sender_stop":
        return _service_action("stop", payload)
    if action == "sender_restart":
        return _service_action("restart", payload)
    if action == "update_control_plane":
        return _update_control_plane(payload)
    raise HelperRequestError("unsupported_action", f"Unsupported helper action: {action}")


def _handle_client(connection: socket.socket) -> None:
    with connection:
        connection.settimeout(5.0)
        _validate_peer(connection)
        data = b""
        while b"\n" not in data:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                raise HelperRequestError("invalid_request", "Helper request exceeds 64 KiB")

        if not data:
            raise HelperRequestError("invalid_request", "No helper request payload received")

        try:
            request = json.loads(data.decode("utf-8").strip())
        except json.JSONDecodeError as exc:
            raise HelperRequestError("invalid_request", "Helper request was not valid JSON") from exc

        if not isinstance(request, dict):
            raise HelperRequestError("invalid_request", "Helper request must be an object")
        action = request.get("action")
        actor = request.get("actor") or {}
        payload = request.get("payload") or {}
        if not isinstance(action, str):
            raise HelperRequestError("invalid_request", "Helper action is missing")
        if not isinstance(actor, dict):
            raise HelperRequestError("invalid_request", "Helper actor must be an object")
        if not isinstance(payload, dict):
            raise HelperRequestError("invalid_request", "Helper payload must be an object")

        LOGGER.info("helper action requested: action=%s actor=%s", action, _actor_label(actor))
        try:
            response_data = _dispatch(action, payload)
            LOGGER.info("helper action succeeded: action=%s actor=%s", action, _actor_label(actor))
            response = {"ok": True, "data": response_data}
        except HelperRequestError as exc:
            LOGGER.warning("helper action failed: action=%s actor=%s error=%s", action, _actor_label(actor), exc.message)
            response = {"ok": False, "error": exc.message, "error_code": exc.error_code, "details": exc.details}

        connection.sendall((json.dumps(response) + "\n").encode("utf-8"))


def _serve() -> None:
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCKET_PATH))
    _ensure_socket_permissions()
    server.listen()
    server.settimeout(1.0)
    LOGGER.info("host control helper listening on %s", SOCKET_PATH)

    try:
        while not STOP_EVENT.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                if STOP_EVENT.is_set():
                    break
                raise
            try:
                _handle_client(connection)
            except HelperRequestError as exc:
                response = {"ok": False, "error": exc.message, "error_code": exc.error_code, "details": exc.details}
                try:
                    connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except OSError:
                    pass
                connection.close()
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                LOGGER.exception("helper request crashed: %s", exc)
                response = {"ok": False, "error": "Helper request crashed", "error_code": "internal_error", "details": {}}
                try:
                    connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except OSError:
                    pass
                connection.close()
    finally:
        server.close()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()


def _stop(*_: Any) -> None:
    STOP_EVENT.set()


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    _serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
