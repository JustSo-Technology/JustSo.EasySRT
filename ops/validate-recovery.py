#!/usr/bin/env python3
"""Real-media recovery acceptance using the production runtime generator.

Run with the backend's Python environment on an isolated Ubuntu 24.04 host.
Only loopback test streams and temporary files/processes are created.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.settings import settings
from app.schemas.config import AppConfig, SiteConfig
from app.schemas.recovery import RecoveryPolicy
from app.services.config_service import build_runtime_config

spec = importlib.util.spec_from_file_location("telemetry_fixture", ROOT / "ops/validate-telemetry.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def wait_status(path, process, predicate, seconds=25):
    deadline = time.monotonic() + seconds
    latest = {}
    while time.monotonic() < deadline:
        if path.exists():
            latest = json.loads(path.read_text())
            if predicate(latest):
                return latest
        if process.poll() is not None:
            raise AssertionError(f"Supervisor exited {process.returncode}: {latest}")
        time.sleep(.1)
    raise AssertionError(f"Status deadline exceeded: {latest}")


class Run:
    def __init__(self, directory, source, receiver, video=False, url=None):
        directory.mkdir()
        self.status = directory / "status.json"
        self.runtime = directory / "applied_sender.json"
        site = SiteConfig.model_validate({
            "input": {"name": "Silent source", "url": url or source.url},
            "destination": {"name": "Isolated receiver", "protocol": "srt", "host": "127.0.0.1", "port": receiver.port},
            "profile": {"name": "Telemetry rehearsal", "enable_video": video, "video_source": "black_test_frames" if video else "none",
                        "video_bitrate_kbps": 100, "video_resolution": "320x240"},
        })
        runtime = build_runtime_config(AppConfig(), site)
        self.runtime.write_text(runtime.model_dump_json())
        self.log = (directory / "transitions.log").open("w")
        self.process = subprocess.Popen([sys.executable, str(ROOT / "ops/sender-supervisor.py"), "--runtime", str(self.runtime),
                                         "--status", str(self.status)], stdout=self.log, stderr=self.log, start_new_session=True)

    def healthy(self, after_attempt=0):
        return wait_status(self.status, self.process, lambda s: s["state"] == "healthy" and s["attempt"] > after_attempt,
                           seconds=max(25, settings.recovery.startup_seconds + settings.recovery.retry_max_seconds + 10))

    def close(self):
        fixture.stop(self.process)
        self.log.close()


def case(directory, media, video, fault):
    source, receiver = fixture.Source(media), fixture.Receiver()
    run = None
    try:
        run = Run(directory, source, receiver, video)
        initial = run.healthy()
        old_pid, old_attempt = initial["child_pid"], initial["attempt"]
        # Change the candidate on disk without changing this run's applied file.
        candidate = directory / "runtime_config.json"
        candidate.write_text('{"destination":"must-not-be-applied"}')
        started = time.monotonic()
        if fault.startswith("input"):
            source.mode = "stall" if fault == "input_stall" else "disconnect"
        elif fault == "output_stall":
            receiver.flow = False
        elif fault == "hung_child":
            os.kill(old_pid, signal.SIGSTOP)
        else:
            receiver.close()
        failed = wait_status(run.status, run.process, lambda s: s["state"] in {"degraded", "retrying"} and s["last_failure_at"] is not None)
        detection = time.monotonic() - started
        receiver.close()
        receiver = fixture.Receiver(receiver.port)
        source.mode = "flow"
        restored = time.monotonic()
        recovered = run.healthy(after_attempt=old_attempt)
        deadline = time.monotonic() + 5
        while receiver.bytes == 0 and time.monotonic() < deadline:
            time.sleep(.1)
        assert receiver.bytes > 0, "No source audio was received after recovery"
        assert recovered["last_recovery_at"]
        assert recovered["child_pid"] != old_pid
        assert recovered["config_id"] == initial["config_id"]
        assert recovered["summary"] == initial["summary"]
        restore_seconds = time.monotonic() - restored
        # SIGINT is what the production systemd unit sends on intentional Stop.
        run.process.send_signal(signal.SIGINT)
        assert run.process.wait(12) == 0
        stopped = json.loads(run.status.read_text())
        assert stopped["state"] == "stopped" and stopped["next_retry_at"] is None
        result = {"video": video, "fault": fault, "passed": True, "reason": failed["reason"],
                  "detection_seconds": round(detection, 3), "restore_seconds": round(restore_seconds, 3),
                  "attempts": recovered["attempt"], "decoded_audio_bytes": receiver.bytes,
                  "applied_configuration_preserved": True}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if run:
            run.close()
        receiver.close()
        source.close()


def stopped_retry(directory, media):
    source, receiver = fixture.Source(media), fixture.Receiver()
    run = None
    try:
        run = Run(directory, source, receiver)
        initial = run.healthy()
        source.mode = "stall"
        wait_status(run.status, run.process, lambda s: s["state"] == "retrying")
        run.process.send_signal(signal.SIGINT)
        assert run.process.wait(12) == 0
        stopped = json.loads(run.status.read_text())
        assert stopped["state"] == "stopped" and not stopped["desired_running"]
        source.mode = "flow"
        time.sleep(3)
        assert json.loads(run.status.read_text())["attempt"] == stopped["attempt"]
        try:
            os.kill(initial["child_pid"], 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("Stopped child survived")
        result = {"fault": "stop_during_backoff", "passed": True, "attempts": stopped["attempt"]}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if run:
            run.close()
        receiver.close()
        source.close()


def finite_file(directory, media_path):
    receiver = fixture.Receiver()
    run = None
    try:
        run = Run(directory, None, receiver, video=True, url=media_path.as_uri())
        wait_status(run.status, run.process, lambda s: s["state"] == "stopped" and s["reason"] == "file_complete", seconds=15)
        assert run.process.wait(3) == 0
        assert json.loads(run.status.read_text())["attempt"] == 1
        assert receiver.bytes > 0
        result = {"fault": "finite_file_with_video", "passed": True, "attempts": 1, "decoded_audio_bytes": receiver.bytes}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if run:
            run.close()
        receiver.close()


def persistent_failure(directory, media):
    source, receiver = fixture.Source(media), fixture.Receiver()
    source.mode = "stall"
    run = None
    try:
        run = Run(directory, source, receiver)
        status = wait_status(run.status, run.process, lambda s: s["state"] == "retrying" and s["retry_count"] >= 3)
        assert status["state"] != "healthy"
        delays = []
        for event in status["events"]:
            if event["state"] == "retrying":
                from datetime import datetime
                delay = (datetime.fromisoformat(event["next_retry_at"]) - datetime.fromisoformat(event["at"])).total_seconds()
                assert .7 <= delay <= 2
                delays.append(round(delay, 3))
        result = {"fault": "persistent_failure", "passed": True, "retry_delays": delays}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if run:
            run.close()
        receiver.close()
        source.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fault", choices=["input_stall", "input_disconnect", "output_stall", "output_disconnect", "hung_child"])
    parser.add_argument("--defaults", action="store_true", help="Also exercise the shipping deadlines (use with --fault)")
    args = parser.parse_args()
    if not args.defaults:
        settings.recovery = RecoveryPolicy(startup_seconds=15, input_stall_seconds=3, output_stall_seconds=3,
                                           io_timeout_seconds=2, retry_initial_seconds=1, retry_max_seconds=2, stable_seconds=5)
    with tempfile.TemporaryDirectory(prefix="easysrt-recovery-") as tmp:
        root = Path(tmp)
        media_path = root / "silence.ts"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-t", "600", "-c:a", "mp2", "-b:a", "256k", "-f", "mpegts", "-muxrate", "600k", str(media_path)], check=True)
        media = media_path.read_bytes()
        short_file = root / "short.ts"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(media_path),
                        "-t", "2", "-c:a", "copy", str(short_file)], check=True)
        # An independent sender runs throughout the fault matrix.
        independent_source, independent_receiver = fixture.Source(media), fixture.Receiver()
        independent = Run(root / "independent", independent_source, independent_receiver)
        try:
            baseline = independent.healthy()
            cases = [case(root / f"{video}-{fault}", media, video, fault)
                     for video in [False, True]
                     for fault in ([args.fault] if args.fault else ["input_stall", "input_disconnect", "output_stall", "output_disconnect", "hung_child"])]
            if not args.defaults:
                cases.append(stopped_retry(root / "stop-backoff", media))
                cases.append(finite_file(root / "file-complete", short_file))
                cases.append(persistent_failure(root / "persistent", media))
            final = json.loads(independent.status.read_text())
            assert final["state"] == "healthy" and final["child_pid"] == baseline["child_pid"]
            assert final["attempt"] == baseline["attempt"] == 1
            cases.append({"fault": "second_instance_isolation", "passed": True, "attempts": 1})
        finally:
            independent.close()
            independent_receiver.close()
            independent_source.close()
    report = {"passed": True, "policy": settings.recovery.model_dump(), "cases": cases}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
