import importlib.util
import json
import math
from pathlib import Path
import time

import pytest
from pydantic import ValidationError

from app.core.settings import Settings, settings
from app.schemas.recovery import RecoveryPolicy
from app.services.config_service import build_runtime_config, load_bundle, migrate_legacy_runtime, save_bundle
from app.services.sender_health import read_sender_health


@pytest.fixture
def supervisor_module():
    path = Path(__file__).resolve().parents[2] / "ops/sender-supervisor.py"
    spec = importlib.util.spec_from_file_location("sender_supervisor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_black_video_progress_cannot_hide_lost_source_audio(supervisor_module):
    source, output = supervisor_module.Counter(), supervisor_module.Counter()
    source.observe(48000, 1)
    output.observe(600000, 1)
    output.observe(1800000, 20)
    assert supervisor_module.stall_reason(source, output, 20, 0, RecoveryPolicy().model_dump()) == "input_stalled"
    assert supervisor_module.stall_reason(source, output, 40, 0, RecoveryPolicy().model_dump()) == "media_stalled"


def test_keepalive_or_unchanged_counter_does_not_refresh_health(supervisor_module, tmp_path):
    runtime = build_runtime_config(load_bundle().app, load_bundle().site).model_dump()
    supervisor = supervisor_module.Supervisor(runtime, tmp_path / "status.json")
    supervisor.observe_line("input", b"1 48000 1.0", 1)
    supervisor.observe_line("output", b"total_size=1000", 1)
    for line in [b"total_size=1000", b"progress=continue", b"out_time_us=30000000", b"total_size=N/A"]:
        supervisor.observe_line("output", line, 30)
    assert supervisor.output.at == 1
    assert supervisor_module.stall_reason(supervisor.source, supervisor.output, 30, 0, runtime["recovery"]) == "media_stalled"


def test_missing_audio_never_finishes_connecting(supervisor_module):
    source, output = supervisor_module.Counter(), supervisor_module.Counter()
    output.observe(99999, 30)
    assert supervisor_module.stall_reason(source, output, 31, 0, RecoveryPolicy().model_dump()) == "startup_timeout"


def test_backoff_is_bounded_and_dead_time_does_not_reset_it(supervisor_module, tmp_path):
    policy = RecoveryPolicy().model_dump()
    assert [supervisor_module.retry_delay(n, policy, lambda low, high: high) for n in range(7)] == [2, 4, 8, 16, 30, 30, 30]
    supervisor = supervisor_module.Supervisor(build_runtime_config(load_bundle().app, load_bundle().site).model_dump(), tmp_path / "s.json")
    supervisor.source.observe(1, 10)
    supervisor.output.observe(1, 40)
    assert not supervisor.sustained_progress(1)
    supervisor.source.observe(2, 40)
    assert supervisor.sustained_progress(1)


def test_stderr_never_persists_credentials(supervisor_module, tmp_path, capsys):
    runtime = build_runtime_config(load_bundle().app, load_bundle().site).model_dump()
    supervisor = supervisor_module.Supervisor(runtime, tmp_path / "s.json")
    supervisor.observe_line("error", b"Failed opening https://user:secret@host/live?token=private", 1)
    supervisor.observe_line("error", b"Error during demuxing: https://user:secret@host/live?token=private", 2)
    supervisor.transition("degraded", "input_error")
    assert "secret" not in supervisor.status_path.read_text() + capsys.readouterr().out
    assert "private" not in supervisor.status_path.read_text()


def test_useful_http_error_context_is_static_and_redacted(supervisor_module, tmp_path, capsys):
    runtime = build_runtime_config(load_bundle().app, load_bundle().site).model_dump()
    supervisor = supervisor_module.Supervisor(runtime, tmp_path / "s.json")
    supervisor.observe_line("error", b"HTTP error 403 Forbidden https://user:secret@host/live?token=private", 1)
    supervisor.transition("degraded", "input_error")
    output = capsys.readouterr().out
    assert "Input server returned HTTP 403." in output
    assert "secret" not in output and "private" not in output


@pytest.mark.parametrize("policy", [
    {"startup_seconds": math.nan}, {"input_stall_seconds": 0}, {"output_stall_seconds": 301},
    {"retry_initial_seconds": 20, "retry_max_seconds": 1}, {"startup_seconds": 5, "io_timeout_seconds": 20},
])
def test_invalid_policy_rejected(policy):
    with pytest.raises(ValidationError):
        RecoveryPolicy(**policy)


def test_nested_host_policy_settings(monkeypatch):
    monkeypatch.setenv("EASYSRT_RECOVERY__INPUT_STALL_SECONDS", "25")
    assert Settings(_env_file=None).recovery.input_stall_seconds == 25


def test_runtime_manifest_and_old_import_schema_are_separate(tmp_path):
    bundle = save_bundle(load_bundle().app, load_bundle().site)
    assert bundle.runtime.ffmpeg_args[-1].startswith("srt://")
    assert "-rw_timeout" in bundle.runtime.ffmpeg_args
    assert "-flush_packets" in bundle.runtime.ffmpeg_args
    assert bundle.runtime.config_id
    assert set(bundle.site.model_dump()) == {"input", "destination", "profile"}
    applied = settings.sender_env_path.with_name("applied_sender.json")
    applied.write_text(bundle.runtime.model_dump_json())
    original = applied.read_bytes()
    changed = bundle.site.model_copy(update={"destination": bundle.site.destination.model_copy(update={"port": 19000})})
    assert save_bundle(bundle.app, changed).runtime.config_id != bundle.runtime.config_id
    assert applied.read_bytes() == original


def test_legacy_migration_only_refreshes_candidate():
    bundle = save_bundle(load_bundle().app, load_bundle().site)
    old = {key: value for key, value in bundle.runtime.model_dump().items()
           if key in {"ffmpeg_command", "service_name", "generated_from_station", "sender_env_path"}}
    settings.runtime_config_path.write_text(json.dumps(old))
    applied = settings.sender_env_path.with_name("applied_sender.json")
    applied.write_text("old applied data")
    migrate_legacy_runtime()
    assert json.loads(settings.runtime_config_path.read_text())["ffmpeg_args"]
    assert applied.read_text() == "old applied data"


def test_changed_host_policy_refreshes_candidate_without_touching_applied(monkeypatch):
    bundle = save_bundle(load_bundle().app, load_bundle().site)
    applied = settings.sender_env_path.with_name("applied_sender.json")
    applied.write_text(bundle.runtime.model_dump_json())
    previous = applied.read_bytes()
    monkeypatch.setattr(settings, "recovery", RecoveryPolicy(input_stall_seconds=25))
    migrate_legacy_runtime()
    assert json.loads(settings.runtime_config_path.read_text())["recovery"]["input_stall_seconds"] == 25
    assert applied.read_bytes() == previous


def write_health(**changes):
    payload = {"schema_version": 1, "state": "healthy", "supervisor_pid": 123, "invocation_id": "live",
               "heartbeat_monotonic": time.monotonic(),
               "input": {"value": 48000, "age_seconds": .1}, "output": {"value": 10000, "age_seconds": .1},
               "policy": RecoveryPolicy().model_dump(), **changes}
    path = settings.sender_env_path.with_name("sender_status.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_only_fresh_matching_process_evidence_can_report_healthy():
    write_health()
    result = {"main_pid": 123, "invocation_id": "live"}
    assert read_sender_health("active", result).state == "healthy"
    assert read_sender_health("active", {**result, "main_pid": 456}).state == "unknown"
    assert read_sender_health("active", {**result, "invocation_id": "previous"}).state == "unknown"
    assert read_sender_health("inactive", result).state == "stopped"
    assert read_sender_health("unavailable", result).state == "unknown"
    write_health(heartbeat_monotonic=time.monotonic() - 5)
    assert read_sender_health("active", result).state == "unknown"
    write_health(input={"age_seconds": 16})
    assert read_sender_health("active", result).state == "degraded"


def test_completed_file_remains_stopped_with_its_terminal_reason():
    write_health(state="stopped", reason="file_complete", desired_running=False)
    status = read_sender_health("inactive", {"main_pid": 0})
    assert status.state == "stopped" and status.reason == "file_complete"


def test_unsupported_manifest_fails_without_launch(supervisor_module, tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text('{"schema_version": 2, "ffmpeg_args": ["ffmpeg", "anything"]}')
    with pytest.raises(ValueError):
        supervisor_module.load_runtime(path)
