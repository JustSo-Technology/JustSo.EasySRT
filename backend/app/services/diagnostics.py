import platform
import shutil
import sys

from app.core.settings import settings
from app.schemas.system import DiagnosticsResponse, SystemInfo
from app.services.health_checks import collect_diagnostics_checks
from app.version import APP_VERSION, installed_commit


def get_system_info() -> SystemInfo:
    return SystemInfo(
        app_version=APP_VERSION,
        installed_commit=installed_commit(),
        hostname=platform.node(),
        platform=sys.platform,
        ffmpeg_available=shutil.which(settings.ffmpeg_binary) is not None,
        ffmpeg_binary=settings.ffmpeg_binary,
        config_path=str(settings.site_config_path.resolve()),
        data_path=str(settings.data_dir.resolve()),
    )


def get_diagnostics() -> DiagnosticsResponse:
    return DiagnosticsResponse(checks=collect_diagnostics_checks())
