from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.schemas.recovery import RecoveryPolicy


class Settings(BaseSettings):
    app_name: str = "JustSo.EasySRT"
    api_prefix: str = "/api"
    environment: str = "development"
    secret_key: str = "dev-change-me"
    app_root: Path = Path("/opt/justso-easysrt")
    data_dir: Path = Path("data")
    sqlite_path: Path = Path("data/easysrt.db")
    app_config_path: Path = Path("data/app_config.json")
    site_config_path: Path = Path("data/site_config.json")
    runtime_config_path: Path = Path("data/runtime_config.json")
    sender_env_path: Path = Path("data/sender.env")
    redundancy_state_path: Path = Path("data/redundancy_state.json")
    update_state_path: Path = Path("data/update-job.json")
    update_log_path: Path = Path("data/update-job.log")
    ffmpeg_binary: str = "ffmpeg"
    sender_service_name: str = "easysrt-sender"
    recovery: RecoveryPolicy = RecoveryPolicy()
    update_repo_url: str = "https://github.com/JustSo-Technology/JustSo.EasySRT.git"
    update_repo_ref: str = "main"
    update_script_path: Path = Path("/usr/local/lib/justso-easysrt/update-ubuntu.sh")
    helper_socket_path: Path = Path("/run/justso-easysrt/helper.sock")
    helper_request_timeout_seconds: float = 35.0
    github_token: str | None = None
    session_cookie_name: str = "easysrt_session"
    session_max_age_seconds: int = 60 * 60 * 12
    session_cookie_secure: bool = False
    allow_insecure_http: bool = False
    frontend_origin: str = "http://localhost:5173"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    updater_port: int = 5174
    updater_public_origin: str | None = None
    updater_token_ttl_seconds: int = 300
    updater_session_ttl_seconds: int = 12 * 60 * 60

    model_config = SettingsConfigDict(env_prefix="EASYSRT_", env_file=".env", env_nested_delimiter="__", extra="ignore")

    @property
    def allowed_hosts(self) -> list[str]:
        if self.environment.lower() != "production":
            return ["*"]
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.environment.lower() != "production":
            return self

        if self.secret_key == "dev-change-me" or len(self.secret_key) < 32:
            raise ValueError("EASYSRT_SECRET_KEY must be a random value of at least 32 characters in production")

        uses_https = self.frontend_origin.lower().startswith("https://")
        if not uses_https and not self.allow_insecure_http:
            raise ValueError(
                "Production HTTP requires the explicit EASYSRT_ALLOW_INSECURE_HTTP=true opt-in; "
                "internet-facing deployments must use HTTPS"
            )
        if uses_https and not self.session_cookie_secure:
            raise ValueError("HTTPS deployments must set EASYSRT_SESSION_COOKIE_SECURE=true")
        if self.session_cookie_secure and not uses_https:
            raise ValueError("Secure session cookies require an HTTPS EASYSRT_FRONTEND_ORIGIN")
        return self


settings = Settings()
