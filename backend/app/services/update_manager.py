from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from fastapi import HTTPException, status

from app.core.settings import settings
from app.models.auth import User
from app.schemas.system import UpdateJobStatus, UpdateStatus
from app.services.host_control import HostControlError, request_helper

_STATE_LOCK = RLock()
_SENDER_IMPACT = "none_expected"
_SENDER_MESSAGE = "This update runs through the local host control helper. It restarts the control plane only, and the live sender is not restarted automatically."
_GIT_TIMEOUT_SECONDS = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_command() -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="git is not available on this system")
    return [git]


def _build_repo_url() -> str:
    token = settings.github_token
    repo_url = settings.update_repo_url
    if token and repo_url.startswith("https://github.com/"):
        return repo_url.replace("https://github.com/", f"https://x-access-token:{token}@github.com/")
    return repo_url


def _run_git(*args: str, cwd: Path | None = None, repo_url: str | None = None) -> subprocess.CompletedProcess[str]:
    command = _git_command()
    env = os.environ.copy()
    if settings.github_token:
        env["GITHUB_TOKEN"] = settings.github_token
    final_args = list(args)
    if repo_url is not None:
        final_args = [repo_url, *final_args]
    try:
        return subprocess.run(
            [*command, *final_args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            [*command, *final_args],
            1,
            stdout=exc.stdout or "",
            stderr=f"git command timed out after {_GIT_TIMEOUT_SECONDS}s",
        )


def _installed_commit() -> str | None:
    result = _run_git("-C", str(settings.app_root), "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _latest_commit() -> str:
    repo_url = _build_repo_url()
    ref = settings.update_repo_ref
    refs = [ref] if ref.startswith("refs/") else [f"refs/heads/{ref}", f"refs/tags/{ref}"]
    patterns = [pattern for ref_name in refs for pattern in (ref_name, f"{ref_name}^{{}}")]
    result = _run_git("ls-remote", repo_url, *patterns)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "Unable to query remote repo"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=stderr)
    remote_refs = {}
    for line in result.stdout.strip().splitlines():
        commit, ref_name = line.split()
        remote_refs[ref_name] = commit
    matches = [ref_name for ref_name in refs if ref_name in remote_refs]
    if len(matches) > 1:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Ambiguous ref {ref}; configure refs/heads/ or refs/tags/ explicitly")
    if not matches:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Ref {settings.update_repo_ref} not found")
    match = matches[0]
    # Annotated tags identify a tag object; compare the peeled commit to HEAD.
    return remote_refs.get(f"{match}^{{}}", remote_refs[match])


def _state_path() -> Path:
    return Path(settings.update_state_path)


def _log_path() -> Path:
    return Path(settings.update_log_path)


def _ensure_state_dir() -> None:
    _state_path().parent.mkdir(parents=True, exist_ok=True)


def _read_state() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _write_state(payload: dict) -> None:
    _ensure_state_dir()
    _state_path().write_text(json.dumps(payload, indent=2, sort_keys=True))


def _read_log_lines(limit: int = 300) -> list[str]:
    path = _log_path()
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    return lines[-limit:]


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False

    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        contents = stat_path.read_text(encoding="utf-8")
    except OSError:
        return True

    fields = contents.split()
    if len(fields) > 2 and fields[2] == "Z":
        return False
    return True


def _normalize_job_status(raw_status: str, pid: int | None) -> str:
    if raw_status == "running" and not _pid_running(pid):
        return "failed"
    return raw_status or "idle"


def _reconcile_state(state: dict) -> dict:
    installed_commit = _installed_commit()
    latest_commit = state.get("latest_commit")
    log_lines = _read_log_lines()

    if (
        state.get("job_status") in {"running", "failed"}
        and installed_commit
        and latest_commit
        and installed_commit == latest_commit
        and not state.get("error")
        and not log_lines
    ):
        state["job_status"] = "succeeded"
        state["current_step"] = "Update completed"
        state["finished_at"] = state.get("finished_at") or _now_iso()
        state["installed_commit_after"] = installed_commit
        _write_state(state)
        return state

    if state.get("job_status") != "running":
        return state
    if _pid_running(state.get("pid")):
        return state

    state["job_status"] = "failed"
    state["error"] = state.get("error") or "Update process exited before reporting completion."
    state["finished_at"] = state.get("finished_at") or _now_iso()
    state["installed_commit_after"] = state.get("installed_commit_after") or installed_commit
    _write_state(state)
    return state


def _build_status_payload(state: dict) -> tuple[dict, list[str]]:
    installed_commit = _installed_commit()
    pid = state.get("pid")
    job_status = _normalize_job_status(state.get("job_status", "idle"), pid)
    latest_commit = state.get("latest_commit")
    update_available = bool(installed_commit and latest_commit and installed_commit != latest_commit)
    if job_status == "succeeded":
        update_available = False
    return (
        {
            "repo_url": settings.update_repo_url,
            "repo_ref": settings.update_repo_ref,
            "installed_commit": installed_commit,
            "latest_commit": latest_commit,
            "update_available": update_available,
            "checked_at": state.get("checked_at"),
            "job_status": job_status,
            "current_step": state.get("current_step"),
            "error": state.get("error"),
            "backup_path": state.get("backup_path"),
            "stash_ref": state.get("stash_ref"),
            "rollback_succeeded": state.get("rollback_succeeded"),
            "sender_impact": _SENDER_IMPACT,
            "sender_message": _SENDER_MESSAGE,
        },
        _read_log_lines(),
    )


def get_update_status() -> UpdateStatus:
    with _STATE_LOCK:
        state = _reconcile_state(_read_state())
        payload, log_lines = _build_status_payload(state)
        payload["log_lines"] = log_lines
        return UpdateStatus(**payload)


def check_for_updates() -> UpdateStatus:
    with _STATE_LOCK:
        state = _reconcile_state(_read_state())
        state["checked_at"] = _now_iso()
        state["latest_commit"] = _latest_commit()
        if state.get("job_status") != "running":
            state["job_status"] = "idle"
            state["current_step"] = None
            state["finished_at"] = None
        state["error"] = None
        _write_state(state)
        payload, log_lines = _build_status_payload(state)
        payload["log_lines"] = log_lines
        return UpdateStatus(**payload)


def get_update_job() -> UpdateJobStatus:
    with _STATE_LOCK:
        state = _reconcile_state(_read_state())
        payload, log_lines = _build_status_payload(state)
        return UpdateJobStatus(
            repo_url=payload["repo_url"],
            repo_ref=payload["repo_ref"],
            installed_commit_before=state.get("installed_commit_before") or payload["installed_commit"],
            installed_commit_after=state.get("installed_commit_after") or payload["installed_commit"],
            latest_commit=payload["latest_commit"],
            checked_at=payload["checked_at"],
            job_status=payload["job_status"],
            current_step=payload["current_step"],
            log_lines=log_lines,
            error=payload["error"],
            backup_path=payload["backup_path"],
            stash_ref=payload["stash_ref"],
            rollback_succeeded=payload["rollback_succeeded"],
            started_at=state.get("started_at"),
            finished_at=state.get("finished_at"),
            sender_impact=_SENDER_IMPACT,
            sender_message=_SENDER_MESSAGE,
        )


def start_update_job(user: User) -> UpdateJobStatus:
    with _STATE_LOCK:
        state = _reconcile_state(_read_state())
        running_status = _normalize_job_status(state.get("job_status", "idle"), state.get("pid"))
        if running_status == "running":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An update is already running")

        installed_commit = _installed_commit()
        latest_commit = state.get("latest_commit") or _latest_commit()
        _ensure_state_dir()
        _log_path().write_text("")

        script_path = Path(settings.update_script_path)
        if not script_path.exists():
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Update script not found at {script_path}")

        initial_state = {
            "repo_url": settings.update_repo_url,
            "repo_ref": settings.update_repo_ref,
            "job_status": "running",
            "current_step": "Preparing update",
            "checked_at": state.get("checked_at") or _now_iso(),
            "started_at": _now_iso(),
            "finished_at": None,
            "installed_commit_before": installed_commit,
            "installed_commit_after": installed_commit,
            "latest_commit": latest_commit,
            "error": None,
            "backup_path": None,
            "stash_ref": None,
            "rollback_succeeded": None,
        }
        _write_state(initial_state)
        try:
            result = request_helper(
                "update_control_plane",
                actor=user,
                payload={
                    "repo_url": settings.update_repo_url,
                    "repo_ref": settings.update_repo_ref,
                    "state_file": str(_state_path()),
                    "log_file": str(_log_path()),
                    "github_token": settings.github_token,
                },
            )
        except HostControlError as exc:
            initial_state["job_status"] = "failed"
            initial_state["finished_at"] = _now_iso()
            initial_state["error"] = exc.message
            initial_state["rollback_succeeded"] = False
            _write_state(initial_state)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc

        initial_state["pid"] = result.get("pid")
        _write_state(initial_state)
        return get_update_job()
