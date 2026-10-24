#!/usr/bin/env python3
"""Isolated systemd/helper/backend acceptance. Requires passwordless sudo.

Creates uniquely named units ONLY in /run and removes them in finally. Never
installs/restarts the actual EasySRT services or changes system boot enablement.
Run with the backend Python environment on a disposable Ubuntu 24.04 VM.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.settings import settings
from app.schemas.config import AppConfig, SiteConfig
from app.schemas.recovery import RecoveryPolicy
from app.services.config_service import migrate_legacy_runtime, save_bundle
from app.services.host_control import HostControlError, request_helper
from app.services.service_control import get_service_status, perform_service_action

spec = importlib.util.spec_from_file_location("telemetry_fixture", ROOT / "ops/validate-telemetry.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def sudo(*args):
    return subprocess.run(["sudo", "-n", *map(str, args)], check=True, capture_output=True, text=True, timeout=35)


def wait_media(state, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = get_service_status()
        if status.media.state == state:
            return status
        time.sleep(.2)
    raise AssertionError(status.model_dump())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    identity = pwd.getpwuid(__import__("os").getuid())
    key = "easysrt-recovery-" + uuid.uuid4().hex[:12]
    protected = Path("/run") / key
    sender_unit, helper_unit = key + "-sender", key + "-helper"
    units = [Path("/run/systemd/system") / f"{name}.service" for name in [sender_unit, helper_unit]]
    events = []
    with tempfile.TemporaryDirectory(prefix=key + "-") as tmp:
        root = Path(tmp)
        app_root = root / "app"
        data = app_root / "backend/data"
        data.mkdir(parents=True)
        settings.app_root = app_root
        settings.data_dir = data
        settings.app_config_path, settings.site_config_path = data / "app_config.json", data / "site_config.json"
        settings.runtime_config_path, settings.sender_env_path = data / "runtime_config.json", data / "sender.env"
        settings.sender_service_name = sender_unit
        settings.helper_socket_path = protected / "socket/helper.sock"
        settings.recovery = RecoveryPolicy(startup_seconds=15, input_stall_seconds=3, output_stall_seconds=3,
                                           io_timeout_seconds=2, retry_initial_seconds=1, retry_max_seconds=2, stable_seconds=5)
        media_path = root / "silent.ts"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-t", "120", "-c:a", "mp2", "-b:a", "256k", "-f", "mpegts", "-muxrate", "600k", str(media_path)], check=True)
        source, receiver = fixture.Source(media_path.read_bytes()), fixture.Receiver()
        site = SiteConfig.model_validate({"input": {"name": "Fixture source", "url": source.url},
            "destination": {"name": "Fixture receiver", "host": "127.0.0.1", "port": receiver.port},
            "profile": {"name": "Fixture profile"}})
        save_bundle(AppConfig(), site)
        sender_text = f"""[Unit]
Description=EasySRT isolated recovery acceptance
StartLimitIntervalSec=60
StartLimitBurst=5
[Service]
User={identity.pw_name}
Group={identity.pw_gid}
ExecStart=/usr/bin/python3 -I {protected}/sender-supervisor.py --runtime {data}/applied_sender.json --status {data}/sender_status.json
Restart=on-failure
RestartSec=1
KillMode=mixed
KillSignal=SIGINT
TimeoutStopSec=12
UMask=0077
NoNewPrivileges=true
"""
        helper_text = f"""[Service]
ExecStart=/usr/bin/python3 -I {protected}/host-control-helper.py
Environment=EASYSRT_APP_USER={identity.pw_name}
Environment=EASYSRT_APP_ROOT={app_root}
Environment=EASYSRT_SENDER_SERVICE={sender_unit}
Environment=EASYSRT_HELPER_SOCKET_PATH={settings.helper_socket_path}
TimeoutStopSec=5
"""
        try:
            sudo("install", "-d", "-o", "root", "-g", "root", "-m", "0755", protected)
            sudo("install", "-d", "-o", "root", "-g", str(identity.pw_gid), "-m", "0750", protected / "socket")
            for filename in ["sender-supervisor.py", "host-control-helper.py"]:
                sudo("install", "-o", "root", "-g", "root", "-m", "0644", ROOT / "ops" / filename, protected / filename)
            for path, text in zip(units, [sender_text, helper_text]):
                candidate = root / path.name
                candidate.write_text(text)
                sudo("install", "-m", "0644", candidate, path)
            sudo("systemctl", "daemon-reload")
            sudo("systemctl", "start", helper_unit)
            for _ in range(50):
                if settings.helper_socket_path.exists():
                    break
                time.sleep(.1)
            before = get_service_status()
            assert before.preflight_ok, before.model_dump()
            assert before.status == "inactive", before.model_dump()
            perform_service_action("start")
            initial = wait_media("healthy")
            original_config = initial.media.config_id
            assert receiver.bytes > 0
            changed = site.model_copy(update={"destination": site.destination.model_copy(update={"port": receiver.port + 1})})
            save_bundle(AppConfig(), changed)
            assert get_service_status().media.pending_config
            try:
                request_helper("sender_start", actor=None)
            except HostControlError as exc:
                assert exc.code == "invalid_transition"
            else:
                raise AssertionError("Duplicate start was accepted")
            assert get_service_status().media.config_id == original_config
            source.mode = "stall"
            wait_media("retrying")
            settings.runtime_config_path.unlink()
            # Invalid candidate/preflight must never prevent an intentional Stop.
            stopped = perform_service_action("stop")
            assert stopped.status == "inactive" and not stopped.preflight_ok
            source.mode = "flow"
            time.sleep(3)
            assert get_service_status().status == "inactive"
            events.append({"case": "stop_during_retry_with_failed_preflight", "passed": True})

            receiver.close()
            receiver = fixture.Receiver(receiver.port)
            save_bundle(AppConfig(), site)
            perform_service_action("start")
            running = wait_media("healthy")
            # A crash restart must reuse the applied route despite saved edits.
            save_bundle(AppConfig(), changed)
            sudo("kill", "-KILL", running.media.supervisor_pid)
            receiver.close()
            receiver = fixture.Receiver(receiver.port)
            restarted = wait_media("healthy")
            assert restarted.media.supervisor_pid != running.media.supervisor_pid
            assert restarted.media.config_id == original_config and restarted.media.pending_config
            assert not Path(f"/proc/{running.media.supervisor_pid}").exists()
            assert running.media.child_pid and not Path(f"/proc/{running.media.child_pid}").exists()
            events.append({"case": "supervisor_crash_cgroup_cleanup_and_applied_runtime", "passed": True})
            sender_pid = restarted.media.supervisor_pid
            sudo("systemctl", "restart", helper_unit)
            time.sleep(.5)
            assert wait_media("healthy").media.supervisor_pid == sender_pid
            events.append({"case": "helper_restart_preserves_live_sender", "passed": True})

            sudo("systemctl", "stop", sender_unit)
            migrate_legacy_runtime()  # The backend startup hook is read/migration only.
            sudo("systemctl", "restart", helper_unit)
            time.sleep(3)
            assert get_service_status().status == "inactive"
            events.append({"case": "direct_systemctl_stop_stays_stopped", "passed": True})

            save_bundle(AppConfig(), site)
            receiver.close()
            receiver = fixture.Receiver(receiver.port)
            perform_service_action("start")
            perform_service_action("stop")
            time.sleep(3)
            assert get_service_status().status == "inactive"
            events.append({"case": "stop_during_startup", "passed": True})
            result = {"passed": True, "cases": events}
            args.report.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result), flush=True)
        finally:
            for name in [sender_unit, helper_unit]:
                subprocess.run(["sudo", "-n", "systemctl", "stop", name], capture_output=True, timeout=35)
            for path in units:
                sudo("rm", "-f", path)
            sudo("systemctl", "daemon-reload")
            subprocess.run(["sudo", "-n", "systemctl", "reset-failed", sender_unit, helper_unit], capture_output=True, timeout=10)
            sudo("rm", "-rf", "--", protected)
            receiver.close()
            source.close()


if __name__ == "__main__":
    main()
