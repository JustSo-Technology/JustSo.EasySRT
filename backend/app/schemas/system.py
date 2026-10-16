from pydantic import BaseModel, Field


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
