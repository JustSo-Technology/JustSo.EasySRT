from pathlib import Path

import pytest

from app.core.db import init_db
from app.core.settings import settings


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep every test write inside a pytest-owned temporary directory."""
    data_dir = tmp_path / "data"
    configured_paths = {
        "data_dir": data_dir,
        "sqlite_path": data_dir / "easysrt.db",
        "app_config_path": data_dir / "app_config.json",
        "site_config_path": data_dir / "site_config.json",
        "runtime_config_path": data_dir / "runtime_config.json",
        "sender_env_path": data_dir / "sender.env",
        "redundancy_state_path": data_dir / "redundancy_state.json",
        "update_state_path": data_dir / "update-job.json",
        "update_log_path": data_dir / "update-job.log",
    }

    temporary_root = tmp_path.resolve()
    for setting_name, configured_path in configured_paths.items():
        resolved_path = configured_path.resolve()
        if not resolved_path.is_relative_to(temporary_root):
            pytest.fail(f"Refusing to configure test path outside {temporary_root}: {resolved_path}")
        monkeypatch.setattr(settings, setting_name, configured_path)
    monkeypatch.setattr(settings, "environment", "test")

    init_db()
    yield
