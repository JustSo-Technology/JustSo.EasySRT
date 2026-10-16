from __future__ import annotations

import os
import subprocess
from pathlib import Path

APP_VERSION = "0.1.0-alpha.1"


def installed_commit() -> str | None:
    configured = os.getenv("EASYSRT_BUILD_COMMIT", "").strip()
    if configured:
        return configured

    repository_root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None
