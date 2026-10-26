import ipaddress
import re
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.recovery import RecoveryPolicy


ALLOWED_INPUT_SCHEMES = {"http", "https", "udp", "rtp", "rtsp", "rtmp", "srt", "file"}
ALLOWED_DESTINATION_SCHEMES = {"srt", "udp"}
ALLOWED_SAMPLE_RATES = {32000, 44100, 48000}
ALLOWED_VIDEO_CODECS = {"mpeg2video", "libx264"}
ALLOWED_VIDEO_SOURCES = {"none", "black_test_frames"}
RESOLUTION_PATTERN = re.compile(r"^\d{2,5}x\d{2,5}$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-zA-Z0-9-]{1,63}(?<!-))(?:\.(?!-)(?:[a-zA-Z0-9-]{1,63}(?<!-)))*$"
)


class InputSource(BaseModel):
    name: str
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ALLOWED_INPUT_SCHEMES:
            allowed = ", ".join(sorted(ALLOWED_INPUT_SCHEMES))
            raise ValueError(f"Input URL scheme must be one of: {allowed}")
        if parsed.scheme == "file":
            if not parsed.path:
                raise ValueError("File input URLs must include a file path")
            return value
        if not parsed.netloc and not parsed.path:
            raise ValueError("Input URL must include a host or path")
        return value


class Destination(BaseModel):
    name: str
    protocol: str = "srt"
    host: str
    port: int = Field(default=16466, ge=1, le=65535)

    @model_validator(mode="before")
    @classmethod
    def normalize_endpoint(cls, value):
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        host = normalized.get("host")
        if isinstance(host, str) and "://" in host:
            parsed = urlparse(host.strip())
            if parsed.scheme:
                normalized["protocol"] = parsed.scheme.lower()
            if parsed.hostname:
                normalized["host"] = parsed.hostname
            if parsed.port:
                normalized["port"] = parsed.port
        return normalized

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        protocol = value.strip().lower()
        if protocol not in ALLOWED_DESTINATION_SCHEMES:
            allowed = ", ".join(sorted(ALLOWED_DESTINATION_SCHEMES))
            raise ValueError(f"Destination protocol must be one of: {allowed}")
        return protocol

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        host = value.strip()
        if not host:
            raise ValueError("Destination host is required")
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            if HOSTNAME_PATTERN.fullmatch(host):
                return host
        raise ValueError("Destination host must be a valid IP address or hostname")


class StreamProfile(BaseModel):
    name: str
    audio_bitrate_kbps: int = Field(default=256, gt=0)
    sample_rate_hz: int = 48000
    channels: int = 2
    srt_latency_ms: int = Field(default=120, gt=0)
    mux_rate_kbps: int = Field(default=600, gt=0)
    pcr_period_ms: int = Field(default=20, gt=0)
    enable_video: bool = False
    video_codec: str = "mpeg2video"
    video_bitrate_kbps: int = Field(default=1000, gt=0)
    video_resolution: str = "1280x720"
    video_frame_rate: int = Field(default=25, gt=0)
    video_source: str = "none"

    @field_validator("sample_rate_hz")
    @classmethod
    def validate_sample_rate(cls, value: int) -> int:
        if value not in ALLOWED_SAMPLE_RATES:
            allowed = ", ".join(str(rate) for rate in sorted(ALLOWED_SAMPLE_RATES))
            raise ValueError(f"Sample rate must be one of: {allowed}")
        return value

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: int) -> int:
        if value not in {1, 2}:
            raise ValueError("Channels must be 1 or 2")
        return value

    @field_validator("video_codec")
    @classmethod
    def validate_video_codec(cls, value: str) -> str:
        if value not in ALLOWED_VIDEO_CODECS:
            allowed = ", ".join(sorted(ALLOWED_VIDEO_CODECS))
            raise ValueError(f"Video codec must be one of: {allowed}")
        return value

    @field_validator("video_resolution")
    @classmethod
    def validate_video_resolution(cls, value: str) -> str:
        resolution = value.strip().lower()
        if not RESOLUTION_PATTERN.fullmatch(resolution):
            raise ValueError("Video resolution must be in WIDTHxHEIGHT format")
        width, height = (int(part) for part in resolution.split("x", 1))
        if width < 16 or height < 16:
            raise ValueError("Video resolution must be at least 16x16")
        return resolution

    @field_validator("video_frame_rate")
    @classmethod
    def validate_video_frame_rate(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Video frame rate must be greater than 0")
        return value

    @field_validator("video_source")
    @classmethod
    def validate_video_source(cls, value: str) -> str:
        if value not in ALLOWED_VIDEO_SOURCES:
            allowed = ", ".join(sorted(ALLOWED_VIDEO_SOURCES))
            raise ValueError(f"Video source must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def validate_rate_consistency(self) -> "StreamProfile":
        required_mux_rate = self.audio_bitrate_kbps + (self.video_bitrate_kbps if self.enable_video else 0)
        if self.mux_rate_kbps <= required_mux_rate:
            raise ValueError("Mux rate must be greater than the enabled audio/video bitrate total")
        if self.enable_video and self.video_source == "none":
            raise ValueError('Video source mapping must be selected when video is enabled')
        return self


class AppConfig(BaseModel):
    station_name: str = "JustSo Demo Station"
    support_contact: str = "support@justso.dev"


class SiteConfig(BaseModel):
    input: InputSource
    destination: Destination
    profile: StreamProfile


class RuntimeConfig(BaseModel):
    ffmpeg_command: str
    service_name: str
    generated_from_station: str
    sender_env_path: str
    snapshot_id: str | None = None
    schema_version: int = 1
    ffmpeg_args: list[str] = Field(default_factory=list)
    input_scheme: str = ""
    recovery: RecoveryPolicy = Field(default_factory=RecoveryPolicy)
    config_id: str = ""
    summary: dict[str, str] = Field(default_factory=dict)


class SelectionSummary(BaseModel):
    id: str
    source_preset_id: str | None = None
    source_revision: int | None = None
    source_name: str
    target: str = "default"
    created_at: datetime


class ConfigBundle(BaseModel):
    app: AppConfig
    site: SiteConfig
    runtime: RuntimeConfig
    selected: SelectionSummary | None = None
    capabilities: list[str] = Field(default_factory=list)


class SavedSiteConfigSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    revision: int


class SavedSiteConfigCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    site: SiteConfig
    overwrite: bool = False
    target_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Saved config name is required")
        return name


class SavedSiteConfigResponse(BaseModel):
    saved_config: SavedSiteConfigSummary


class SavedSiteConfigDetail(SavedSiteConfigResponse):
    bundle: ConfigBundle
    app_digest: str
    runtime_digest: str
    runtime_version: int = 1
    expected_selection_id: str | None


class SavedSiteConfigUpdateRequest(BaseModel):
    site: SiteConfig
    expected_revision: int | None = Field(default=None, ge=1)


class ApplyPresetRequest(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    expected_selection_id: str | None = None
    app_digest: str | None = None
    runtime_digest: str | None = None
    runtime_version: int = 1
    target: str = "default"
    request_id: str = Field(min_length=1, max_length=100)


class SavedSiteConfigRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Saved config name is required")
        return name


class SavedInputEntry(BaseModel):
    id: str
    name: str
    url: str
    created_at: datetime
    updated_at: datetime


class SavedInputCreateRequest(BaseModel):
    input: InputSource


class SavedDestinationEntry(BaseModel):
    id: str
    name: str
    protocol: str = "srt"
    host: str
    port: int
    created_at: datetime
    updated_at: datetime


class SavedDestinationCreateRequest(BaseModel):
    destination: Destination
