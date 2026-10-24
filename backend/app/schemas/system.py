from pydantic import BaseModel, Field
from typing import Literal


class MediaCounter(BaseModel):
    value: int = Field(default=0, ge=0)
    last_progress_at: str | None = None
    age_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SenderHealth(BaseModel):
    state: Literal["stopped", "connecting", "healthy", "degraded", "retrying", "unknown"] = "unknown"
    reason: str = "unavailable"
    detail: str = "Media health is unavailable."
    run_id: str | None = None
    supervisor_pid: int | None = None
    child_pid: int | None = Field(default=None, ge=1)
    invocation_id: str = ""
    config_id: str | None = None
    summary: dict[str, str] = Field(default_factory=dict)
    input: MediaCounter = Field(default_factory=MediaCounter)
    output: MediaCounter = Field(default_factory=MediaCounter)
    attempt: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    next_retry_at: str | None = None
    last_failure_at: str | None = None
    last_recovery_at: str | None = None
    last_exit_code: int | None = None
    heartbeat_at: str | None = None
    heartbeat_monotonic: float = Field(default=0, ge=0, allow_inf_nan=False)
    remote_receipt: Literal["unverified"] = "unverified"
    desired_running: bool = False
    pending_config: bool = False
    policy: dict[str, float] = Field(default_factory=dict)
    events: list[dict] = Field(default_factory=list, max_length=20)
    stderr_tail: list[str] = Field(default_factory=list, max_length=8)


class ServiceStatus(BaseModel):
    service_name: str
    running: bool
    status: str
    detail: str
    allowed_actions: list[str] = Field(default_factory=list)
    preflight_ok: bool = False
    preflight_failures: list[str] = Field(default_factory=list)
    last_command: str | None = None
    last_exit_code: int | None = None
    stderr_tail: str | None = None
    media: SenderHealth = Field(default_factory=SenderHealth)


class LogResponse(BaseModel):
    service_name: str
    lines: list[str]


class DiagnosticCheck(BaseModel):
    name: str
    ok: bool
    detail: str
    severity: str
    category: str
    blocking: bool


class DiagnosticsResponse(BaseModel):
    checks: list[DiagnosticCheck]


class SystemInfo(BaseModel):
    app_version: str
    installed_commit: str | None = None
    hostname: str
    platform: str
    ffmpeg_available: bool
    ffmpeg_binary: str
    config_path: str
    data_path: str


class UpdateStatus(BaseModel):
    repo_url: str
    repo_ref: str
    installed_commit: str | None = None
    latest_commit: str | None = None
    update_available: bool = False
    checked_at: str | None = None
    job_status: str = "idle"
    current_step: str | None = None
    log_lines: list[str] = Field(default_factory=list)
    error: str | None = None
    backup_path: str | None = None
    stash_ref: str | None = None
    rollback_succeeded: bool | None = None
    sender_impact: str = "none_expected"
    sender_message: str = "This update runs through the local host control helper. It restarts the control plane only, and the live sender is not restarted automatically."


class UpdateJobStatus(BaseModel):
    repo_url: str
    repo_ref: str
    installed_commit_before: str | None = None
    installed_commit_after: str | None = None
    latest_commit: str | None = None
    checked_at: str | None = None
    job_status: str = "idle"
    current_step: str | None = None
    log_lines: list[str] = Field(default_factory=list)
    error: str | None = None
    backup_path: str | None = None
    stash_ref: str | None = None
    rollback_succeeded: bool | None = None
    started_at: str | None = None
    finished_at: str | None = None
    sender_impact: str = "none_expected"
    sender_message: str = "This update runs through the local host control helper. It restarts the control plane only, and the live sender is not restarted automatically."


class UpdateLaunchResponse(BaseModel):
    updater_url: str
    expires_at: str
