"""Trust-boundary regressions; never run host commands or change host ownership."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def helper():
    path = Path(__file__).resolve().parents[2] / "ops" / "host-control-helper.py"
    spec = importlib.util.spec_from_file_location("host_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("unsafe", ["writable_parent", "user_owner", "symlink", "hardlink"])
def test_protected_script_rejects_unsafe_ancestry(helper, monkeypatch, unsafe):
    script = Path("/protected/ops/update.sh")
    def metadata(path):
        mode = stat.S_IFREG | 0o755 if path == script else stat.S_IFDIR | 0o755
        uid, links = 0, 1
        if unsafe == "writable_parent" and path == script.parent:
            mode |= 0o020
        if unsafe == "user_owner" and path == script:
            uid = 1000
        if unsafe == "symlink" and path == script.parent:
            mode = stat.S_IFLNK | 0o777
        if unsafe == "hardlink" and path == script:
            links = 2
        return SimpleNamespace(st_mode=mode, st_uid=uid, st_nlink=links)
    monkeypatch.setattr(Path, "lstat", metadata)
    with pytest.raises(helper.HelperRequestError, match="protected|hard links"):
        helper._validate_root_path(script)


@pytest.mark.parametrize("payload", [
    {"repo_url": "https://github.com/attacker/payload.git"},
    {"repo_ref": "attacker-branch"},
    {"state_file": "/etc/sudoers"},
    {"log_file": "../../etc/crontab"},
    {"github_token": "token\nmalicious"},
    {"github_token": "@attacker.example/#"},
])
def test_untrusted_update_inputs_rejected_before_process(helper, monkeypatch, payload):
    monkeypatch.setattr(helper, "_validate_root_path", Mock())
    monkeypatch.setattr(helper, "_update_policy", lambda: {"repo_url": "https://github.com/JustSo-Technology/JustSo.EasySRT.git", "repo_ref": "main"})
    popen = Mock()
    monkeypatch.setattr(helper.subprocess, "Popen", popen)
    with pytest.raises(helper.HelperRequestError):
        helper._update_control_plane(payload)
    popen.assert_not_called()


def test_peer_requires_service_uid_not_just_shared_group(helper, monkeypatch):
    monkeypatch.setattr(helper, "_allowed_uid_gid", lambda: (999, 999))
    monkeypatch.setattr(helper, "_peer_credentials", lambda _: (123, 1000, 999))
    with pytest.raises(helper.HelperRequestError, match="not permitted"):
        helper._validate_peer(Mock())


def test_safe_update_uses_protected_script_and_minimal_environment(helper, monkeypatch, tmp_path):
    monkeypatch.setenv("BASH_ENV", "/tmp/attacker.sh")
    monkeypatch.setenv("PYTHONPATH", "/tmp/attacker")
    monkeypatch.setattr(helper, "_validate_root_path", Mock())
    monkeypatch.setattr(helper, "_update_policy", lambda: {"repo_url": "https://github.com/JustSo-Technology/JustSo.EasySRT.git", "repo_ref": "main"})
    monkeypatch.setattr(helper, "_open_tracking_file", lambda _: os.open(tmp_path / "tracking", os.O_WRONLY | os.O_CREAT, 0o600))
    process = Mock(pid=1234)
    popen = Mock(return_value=process)
    monkeypatch.setattr(helper.subprocess, "Popen", popen)
    monkeypatch.setattr(helper.threading, "Thread", Mock())
    assert helper._update_control_plane({}) == {"pid": 1234}
    args, kwargs = popen.call_args
    assert args[0] == ["/bin/bash", "/usr/local/lib/justso-easysrt/update-ubuntu.sh"]
    assert kwargs["cwd"] == "/"
    assert "BASH_ENV" not in kwargs["env"]
    assert "PYTHONPATH" not in kwargs["env"]
    assert kwargs["env"]["EASYSRT_UPDATE_LOG_FILE"] == "/var/lib/justso-easysrt-updates/update-job.log"


def test_tracking_hardlink_rejected(helper, monkeypatch, tmp_path):
    path = tmp_path / "tracking"
    path.touch()
    monkeypatch.setattr(helper, "_validate_root_path", Mock())
    monkeypatch.setattr(helper, "_allowed_uid_gid", lambda: (999, 999))
    monkeypatch.setattr(helper.os, "fstat", lambda _: SimpleNamespace(st_mode=stat.S_IFREG | 0o660, st_uid=0, st_nlink=2))
    with pytest.raises(helper.HelperRequestError, match="root-owned regular"):
        helper._open_tracking_file(path)


@pytest.mark.parametrize("contents", [
    '{"repo_url":"file:///tmp/payload","repo_ref":"main"}',
    '{"repo_url":"https://github.com.evil/repo/app","repo_ref":"main"}',
    '{"repo_url":"https://github.com/org/app","repo_ref":"--upload-pack=evil"}',
    '[]',
    'broken json',
])
def test_invalid_host_policy_is_rejected(helper, monkeypatch, contents):
    monkeypatch.setattr(helper, "_validate_root_path", Mock())
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: contents)
    with pytest.raises(helper.HelperRequestError):
        helper._update_policy()


def test_tracking_symlink_does_not_follow_target(helper, monkeypatch, tmp_path):
    target = tmp_path / "sensitive"
    target.write_text("untouched")
    link = tmp_path / "tracking"
    link.symlink_to(target)
    monkeypatch.setattr(helper, "_validate_root_path", Mock())
    with pytest.raises(OSError):
        helper._open_tracking_file(link)
    assert target.read_text() == "untouched"


def test_sender_restart_stops_before_pinning_and_starting(helper, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(helper, "SOCKET_PATH", tmp_path / "helper.sock")
    monkeypatch.setattr(helper, "_sender_status", lambda: {"service_state": "active"})
    monkeypatch.setattr(helper, "_pin_sender_runtime", lambda fd, expected, **kw: calls.append("validate" if kw.get("validate_only") else "pin"))
    def run(command, **kwargs):
        calls.append(command[1])
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(helper, "_run_command", run)
    helper._service_action("restart", {"expected_snapshot_id": "11111111-1111-1111-1111-111111111111"})
    assert calls == ["daemon-reload", "validate", "stop", "pin", "reset-failed", "start"]


def test_failed_stop_never_pins_or_starts_replacement(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "SOCKET_PATH", tmp_path / "helper.sock")
    monkeypatch.setattr(helper, "_sender_status", lambda: {"service_state": "active"})
    monkeypatch.setattr(helper, "_run_command", lambda command, **kw: subprocess.CompletedProcess(command, int(command[1] == "stop"), "", ""))
    pin = Mock()
    monkeypatch.setattr(helper, "_pin_sender_runtime", pin)
    with pytest.raises(helper.HelperRequestError, match="could not be stopped"):
        helper._service_action("restart", {"expected_snapshot_id": "11111111-1111-1111-1111-111111111111"})
    pin.assert_called_once()
    assert pin.call_args.kwargs == {"validate_only": True}


def test_helper_commands_have_a_deadline(helper, monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 5
        raise subprocess.TimeoutExpired(args[0], 5)
    monkeypatch.setattr(helper.subprocess, "run", timeout)
    with pytest.raises(helper.HelperRequestError, match="timed out"):
        helper._run_command(["/usr/bin/systemctl", "show", "easysrt-sender"])


def test_abandoned_control_lock_has_a_bounded_wait(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "SOCKET_PATH", tmp_path / "helper.sock")
    times = iter([0, 6])
    monkeypatch.setattr(helper.time, "monotonic", lambda: next(times))
    with (tmp_path / "sender-control.lock").open("a") as occupied:
        helper.fcntl.flock(occupied, helper.fcntl.LOCK_EX)
        with pytest.raises(helper.HelperRequestError, match="still completing"):
            helper._service_action("stop")
