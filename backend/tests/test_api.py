from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from subprocess import CompletedProcess
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app.core.db import init_db
from app.core.settings import settings
from app.main import app
from app.models.auth import User, UserRole
from app.updater import app as updater_app
from app.services import health_checks, service_control, update_manager
from app.services.config_service import load_bundle, save_bundle
from app.services.update_handoff import create_launch_response


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path):
    original_values = {
        "data_dir": settings.data_dir,
        "sqlite_path": settings.sqlite_path,
        "app_config_path": settings.app_config_path,
        "site_config_path": settings.site_config_path,
        "runtime_config_path": settings.runtime_config_path,
        "sender_env_path": settings.sender_env_path,
        "redundancy_state_path": settings.redundancy_state_path,
        "update_state_path": settings.update_state_path,
        "update_log_path": settings.update_log_path,
        "helper_socket_path": settings.helper_socket_path,
    }
    settings.data_dir = tmp_path
    settings.sqlite_path = tmp_path / "easysrt.db"
    settings.app_config_path = tmp_path / "app_config.json"
    settings.site_config_path = tmp_path / "site_config.json"
    settings.runtime_config_path = tmp_path / "runtime_config.json"
    settings.sender_env_path = tmp_path / "sender.env"
    settings.redundancy_state_path = tmp_path / "redundancy_state.json"
    settings.update_state_path = tmp_path / "update-job.json"
    settings.update_log_path = tmp_path / "update-job.log"
    settings.helper_socket_path = tmp_path / "host-control.sock"
    init_db()
    yield
    for key, value in original_values.items():
        setattr(settings, key, value)


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def updater_client() -> TestClient:
    with TestClient(updater_app) as test_client:
        yield test_client


def bootstrap(client: TestClient, username: str = "owner") -> None:
    response = client.post(
        "/api/auth/bootstrap-owner",
        json={"username": username, "password": "supersecurepass", "role": "owner"},
    )
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def login(client: TestClient, username: str = "owner", password: str = "supersecurepass") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


def mock_tooling(
    monkeypatch: pytest.MonkeyPatch,
    ffmpeg_path: str | None = "/usr/bin/ffmpeg",
    systemctl_path: str | None = "/usr/bin/systemctl",
) -> None:
    def fake_which(binary: str) -> str | None:
        if binary == settings.ffmpeg_binary:
            return ffmpeg_path
        if binary == "systemctl":
            return systemctl_path
        if binary == "journalctl":
            return "/usr/bin/journalctl"
        return None

    monkeypatch.setattr(health_checks.shutil, "which", fake_which)
    monkeypatch.setattr(
        health_checks,
        "_resolve_privileged_command",
        lambda binary_name: [fake_which(binary_name)] if fake_which(binary_name) is not None else None,
    )

    def fake_system_checks(command: list[str], *args: str) -> CompletedProcess[str]:
        if args[:1] == ("show",):
            return CompletedProcess([*command, *args], 0, stdout="loaded\n/etc/systemd/system/easysrt-sender.service\n", stderr="")
        if args == ("is-active", settings.sender_service_name):
            return CompletedProcess([*command, *args], 0, stdout="inactive\n", stderr="")
        raise AssertionError(f"Unexpected health check command: {args}")

    monkeypatch.setattr(health_checks, "_run_command", fake_system_checks)


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_bootstrap_status_changes(client: TestClient):
    response = client.get("/api/auth/bootstrap-status")
    assert response.status_code == 200
    assert response.json() == {"requires_bootstrap": True}

    bootstrap(client)

    response = client.get("/api/auth/bootstrap-status")
    assert response.status_code == 200
    assert response.json() == {"requires_bootstrap": False}


def test_owner_can_list_and_create_users(client: TestClient):
    bootstrap(client)

    create_response = client.post(
        "/api/auth/users",
        json={"username": "engineer-one", "password": "engineerpass123", "role": "engineer"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["role"] == "engineer"

    list_response = client.get("/api/auth/users")

    assert list_response.status_code == 200
    usernames = {user["username"] for user in list_response.json()}
    assert {"owner", "engineer-one"} <= usernames


def test_authenticated_write_requires_csrf_token(client: TestClient):
    bootstrap(client)
    client.headers.pop("X-CSRF-Token")

    response = client.post(
        "/api/auth/users",
        json={"username": "engineer-one", "password": "engineerpass123", "role": "engineer"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing or invalid CSRF token"


def test_security_headers_are_present(client: TestClient):
    response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_logout_revokes_server_session(client: TestClient):
    bootstrap(client)

    response = client.post("/api/auth/logout")
    client.headers.pop("X-CSRF-Token")

    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_owner_cannot_remove_own_owner_access(client: TestClient):
    bootstrap(client)
    owner = client.get("/api/auth/users").json()[0]

    response = client.patch(f"/api/auth/users/{owner['id']}", json={"disabled": True})

    assert response.status_code == 400
    assert "own owner access" in response.text


def test_last_owner_cannot_be_demoted(client: TestClient):
    bootstrap(client)
    owner = client.get("/api/auth/users").json()[0]

    response = client.patch(f"/api/auth/users/{owner['id']}", json={"role": "operator"})

    assert response.status_code == 400
    assert "own owner access" in response.text


def test_owner_can_manage_secondary_owner_when_another_owner_exists(client: TestClient):
    bootstrap(client)
    client.post(
        "/api/auth/users",
        json={"username": "owner-two", "password": "owner-two-pass", "role": "owner"},
    )
    users = client.get("/api/auth/users").json()
    second_owner = next(user for user in users if user["username"] == "owner-two")

    response = client.patch(f"/api/auth/users/{second_owner['id']}", json={"disabled": True})

    assert response.status_code == 200
    assert response.json()["disabled"] is True


def test_invalid_site_config_scheme_returns_422(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    payload = bundle.site.model_dump()
    payload["input"]["url"] = "ftp://unsupported.example.com/audio.mp3"

    response = client.put("/api/config/site", json=payload)

    assert response.status_code == 422
    assert "Input URL scheme must be one of" in response.text


def test_invalid_site_config_profile_returns_422(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    payload = bundle.site.model_dump()
    payload["profile"]["channels"] = 6

    response = client.put("/api/config/site", json=payload)

    assert response.status_code == 422
    assert "Channels must be 1 or 2" in response.text


def test_video_requires_source_mapping(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    payload = bundle.site.model_dump()
    payload["profile"]["enable_video"] = True
    payload["profile"]["mux_rate_kbps"] = 2000
    payload["profile"]["video_source"] = "none"

    response = client.put("/api/config/site", json=payload)

    assert response.status_code == 422
    assert "Video source mapping must be selected" in response.text


def test_save_bundle_writes_sender_env_and_converts_latency_to_microseconds():
    bundle = load_bundle()
    saved = save_bundle(bundle.app, bundle.site)

    env_text = settings.sender_env_path.read_text()
    assert "FFMPEG_CMD=" in env_text
    from urllib.parse import parse_qs, urlsplit

    destination = shlex.split(saved.runtime.ffmpeg_command)[-1]
    assert parse_qs(urlsplit(destination).query)["latency"] == [str(bundle.site.profile.srt_latency_ms * 1000)]


def test_save_bundle_generates_black_test_frames_video_command():
    bundle = load_bundle()
    site = bundle.site.model_copy(
        update={
            "profile": bundle.site.profile.model_copy(
                update={
                    "enable_video": True,
                    "video_codec": "libx264",
                    "video_bitrate_kbps": 1500,
                    "video_resolution": "1280x720",
                    "video_frame_rate": 25,
                    "video_source": "black_test_frames",
                    "mux_rate_kbps": 2000,
                }
            )
        }
    )

    saved = save_bundle(bundle.app, site)
    command_args = shlex.split(saved.runtime.ffmpeg_command)

    assert "color=c=black:s=1280x720:r=25" in saved.runtime.ffmpeg_command
    assert "-map 0:a:0" in saved.runtime.ffmpeg_command
    assert "-map 1:v:0" in saved.runtime.ffmpeg_command
    assert "-c:v libx264" in saved.runtime.ffmpeg_command
    assert "-pix_fmt yuv420p" in saved.runtime.ffmpeg_command
    assert "-vn" not in saved.runtime.ffmpeg_command
    assert command_args.index("-c:a") > command_args.index("color=c=black:s=1280x720:r=25")


def test_get_config_returns_derived_runtime(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    save_bundle(bundle.app, bundle.site)
    settings.runtime_config_path.write_text("{}")

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["runtime"]["service_name"] == settings.sender_service_name
    assert response.json()["runtime"]["ffmpeg_command"]


def test_owner_can_save_and_list_named_site_configs(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    payload = {
        "name": "Raw FM to Parents",
        "site": bundle.site.model_dump(),
    }

    create_response = client.post("/api/config/saved", json=payload)

    assert create_response.status_code == 200
    assert create_response.json()["saved_config"]["name"] == "Raw FM to Parents"
    assert create_response.json()["bundle"]["site"]["input"]["name"] == bundle.site.input.name

    list_response = client.get("/api/config/saved")

    assert list_response.status_code == 200
    assert list_response.json()[0]["name"] == "Raw FM to Parents"
    assert list_response.json()[0]["is_active"] is True


def test_loading_saved_site_config_updates_live_bundle(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    payload = {
        "name": "Receiver B",
        "site": {
            **bundle.site.model_dump(),
            "destination": {
                **bundle.site.destination.model_dump(),
                "host": "100.120.133.115",
                "port": 16466,
            },
        },
    }

    save_response = client.post("/api/config/saved", json=payload)
    saved_id = save_response.json()["saved_config"]["id"]

    second_payload = {
        "input": {"name": "Another Feed", "url": "http://example.com/live.mp3"},
        "destination": {"name": "Elsewhere", "host": "stream.example.com", "port": 15000},
        "profile": bundle.site.profile.model_dump(),
    }
    overwrite_response = client.put("/api/config/site", json=second_payload)
    assert overwrite_response.status_code == 200

    load_response = client.post(f"/api/config/saved/{saved_id}/load")

    assert load_response.status_code == 200
    assert load_response.json()["site"]["destination"]["host"] == "100.120.133.115"
    assert load_bundle().site.destination.host == "100.120.133.115"


def test_saving_existing_named_config_requires_overwrite_flag(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    payload = {"name": "Shared Route", "site": bundle.site.model_dump()}

    first_response = client.post("/api/config/saved", json=payload)
    assert first_response.status_code == 200

    second_response = client.post("/api/config/saved", json=payload)
    assert second_response.status_code == 409
    assert "already exists" in second_response.text

    overwrite_response = client.post("/api/config/saved", json={**payload, "overwrite": True})
    assert overwrite_response.status_code == 200


def test_saved_config_can_be_renamed_and_deleted(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    create_response = client.post("/api/config/saved", json={"name": "Original Name", "site": bundle.site.model_dump()})
    saved_id = create_response.json()["saved_config"]["id"]

    rename_response = client.patch(f"/api/config/saved/{saved_id}", json={"name": "Renamed Config"})
    assert rename_response.status_code == 200
    assert rename_response.json()["name"] == "Renamed Config"

    delete_response = client.delete(f"/api/config/saved/{saved_id}")
    assert delete_response.status_code == 200

    list_response = client.get("/api/config/saved")
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_direct_site_update_clears_active_saved_config(client: TestClient):
    bootstrap(client)
    bundle = load_bundle()
    client.post("/api/config/saved", json={"name": "Original Name", "site": bundle.site.model_dump()})

    update_response = client.put(
        "/api/config/site",
        json={
            "input": {"name": "Changed", "url": "http://example.com/live.mp3"},
            "destination": {"name": "Receiver", "host": "stream.example.com", "port": 15000},
            "profile": bundle.site.profile.model_dump(),
        },
    )
    assert update_response.status_code == 200

    list_response = client.get("/api/config/saved")
    assert list_response.status_code == 200
    assert list_response.json()[0]["is_active"] is False


def test_owner_can_save_and_list_inputs_and_destinations(client: TestClient):
    bootstrap(client)

    input_response = client.post("/api/config/saved-inputs", json={"input": {"name": "Raw FM", "url": "http://example.com/live.mp3"}})
    assert input_response.status_code == 200
    assert input_response.json()["name"] == "Raw FM"

    destination_response = client.post(
        "/api/config/saved-destinations",
        json={"destination": {"name": "Parents Receiver", "host": "100.120.133.115", "port": 16466}},
    )
    assert destination_response.status_code == 200
    assert destination_response.json()["host"] == "100.120.133.115"

    saved_inputs_response = client.get("/api/config/saved-inputs")
    assert saved_inputs_response.status_code == 200
    assert saved_inputs_response.json()[0]["url"] == "http://example.com/live.mp3"

    saved_destinations_response = client.get("/api/config/saved-destinations")
    assert saved_destinations_response.status_code == 200
    assert saved_destinations_response.json()[0]["port"] == 16466


def test_saved_input_and_destination_names_must_be_unique(client: TestClient):
    bootstrap(client)
    first_input = client.post("/api/config/saved-inputs", json={"input": {"name": "Raw FM", "url": "http://example.com/live.mp3"}})
    assert first_input.status_code == 200
    second_input = client.post("/api/config/saved-inputs", json={"input": {"name": "Raw FM", "url": "http://example.com/alt.mp3"}})
    assert second_input.status_code == 409

    first_destination = client.post(
        "/api/config/saved-destinations",
        json={"destination": {"name": "Parents Receiver", "host": "100.120.133.115", "port": 16466}},
    )
    assert first_destination.status_code == 200
    second_destination = client.post(
        "/api/config/saved-destinations",
        json={"destination": {"name": "Parents Receiver", "host": "127.0.0.1", "port": 15000}},
    )
    assert second_destination.status_code == 409


def test_service_start_blocks_when_runtime_artifacts_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)
    bundle = load_bundle()
    save_bundle(bundle.app, bundle.site)
    settings.runtime_config_path.unlink()
    mock_tooling(monkeypatch)

    response = client.post("/api/service/start")

    assert response.status_code == 424
    assert response.json()["preflight_ok"] is False
    assert any("runtime-config" in failure for failure in response.json()["preflight_failures"])


def test_service_invalid_transition_returns_409(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)
    save_bundle(load_bundle().app, load_bundle().site)
    mock_tooling(monkeypatch)
    monkeypatch.setattr(
        service_control,
        "request_helper",
        lambda action, *, actor, payload=None: {"service_state": "inactive"} if action == "sender_status" else {},
    )

    response = client.post("/api/service/stop")

    assert response.status_code == 409
    assert response.json()["status"] == "inactive"


def test_service_systemctl_failure_returns_502(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)
    save_bundle(load_bundle().app, load_bundle().site)
    mock_tooling(monkeypatch)

    def fake_request_helper(action: str, *, actor, payload=None):
        if action == "sender_status":
            return {"service_state": "inactive"}
        if action == "sender_start":
            raise service_control.HostControlError(
                "start failed",
                details={"exit_code": 1, "stdout": "", "stderr": "start failed"},
            )
        raise AssertionError(f"Unexpected helper action: {action}")

    monkeypatch.setattr(service_control, "request_helper", fake_request_helper)

    response = client.post("/api/service/start")

    assert response.status_code == 502
    assert response.json()["last_exit_code"] == 1
    assert response.json()["stderr_tail"] == "start failed"


def test_diagnostics_reports_critical_missing_runtime_artifacts(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)
    mock_tooling(monkeypatch, ffmpeg_path=None, systemctl_path=None)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    checks = {check["name"]: check for check in response.json()["checks"]}
    assert checks["ffmpeg-binary"]["severity"] == "critical"
    assert checks["ffmpeg-binary"]["blocking"] is True
    assert checks["config-valid"]["ok"] is True


def test_diagnostics_reports_missing_sender_unit(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)
    save_bundle(load_bundle().app, load_bundle().site)
    mock_tooling(monkeypatch)

    def fake_system_checks(command: list[str], *args: str) -> CompletedProcess[str]:
        if args[:1] == ("show",):
            return CompletedProcess([*command, *args], 1, stdout="", stderr="Unit easysrt-sender.service could not be found.")
        if args == ("is-active", settings.sender_service_name):
            return CompletedProcess([*command, *args], 3, stdout="inactive\n", stderr="")
        raise AssertionError(f"Unexpected health check command: {args}")

    monkeypatch.setattr(health_checks, "_run_command", fake_system_checks)
    monkeypatch.setattr(
        health_checks,
        "check_ffmpeg_version",
        lambda: health_checks._make_check(
            name="ffmpeg-version",
            ok=True,
            detail="ffmpeg version test",
            severity="info",
            category="system",
            blocking=True,
        ),
    )

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    checks = {check["name"]: check for check in response.json()["checks"]}
    assert checks["service-unit-installed"]["ok"] is False
    assert checks["service-unit-installed"]["blocking"] is True
    assert "could not be found" in checks["service-unit-installed"]["detail"]
    assert checks["sender-service-state"]["ok"] is False


def test_diagnostics_input_and_destination_checks_are_stable(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    bootstrap(client)
    bundle = load_bundle()
    input_file = tmp_path / "input.mp3"
    input_file.write_text("demo")
    bundle.site.input.url = input_file.as_uri()
    bundle.site.destination.host = "127.0.0.1"
    save_bundle(bundle.app, bundle.site)
    mock_tooling(monkeypatch)
    monkeypatch.setattr(health_checks, "check_ffmpeg_version", lambda: health_checks._make_check(
        name="ffmpeg-version",
        ok=True,
        detail="ffmpeg version test",
        severity="info",
        category="system",
        blocking=True,
    ))

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    checks = {check["name"]: check for check in response.json()["checks"]}
    assert checks["input-reachability"]["ok"] is True
    assert checks["destination-health"]["category"] == "output"


def test_input_reachability_falls_back_to_get_after_head_400(monkeypatch: pytest.MonkeyPatch):
    bundle = load_bundle()
    bundle.site.input.url = "http://203.35.197.78:8000/Raw1-MB.mp3"

    class FakeResponse:
        def __init__(self, status: int):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    calls: list[str] = []

    def fake_urlopen(request, timeout: int = 5):
        calls.append(request.get_method())
        if request.get_method() == "HEAD":
            raise HTTPError(request.full_url, 400, "Bad Request", hdrs=None, fp=None)
        return FakeResponse(200)

    monkeypatch.setattr(health_checks, "urlopen", fake_urlopen)

    check = health_checks.check_input_reachability(bundle)

    assert calls == ["HEAD", "GET"]
    assert check.ok is True
    assert check.detail == "GET 200 after HEAD fallback"


def test_owner_can_check_for_updates(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)

    monkeypatch.setattr(
        update_manager,
        "check_for_updates",
        lambda: update_manager.UpdateStatus(
            repo_url="https://github.com/JustSo-Technology/JustSo.EasySRT.git",
            repo_ref="main",
            installed_commit="aaaa111",
            latest_commit="bbbb222",
            update_available=True,
            checked_at="2026-03-18T00:00:00+00:00",
            job_status="idle",
            current_step=None,
            log_lines=[],
            error=None,
            backup_path=None,
            stash_ref=None,
            rollback_succeeded=None,
            sender_impact="none_expected",
            sender_message="This update restarts the control plane only. The live sender is not restarted automatically.",
        ),
    )

    response = client.post("/api/update/check")

    assert response.status_code == 200
    assert response.json()["update_available"] is True


def test_non_owner_cannot_access_update_endpoints(client: TestClient):
    bootstrap(client)
    create_response = client.post(
        "/api/auth/users",
        json={"username": "engineer-one", "password": "engineerpass123", "role": "engineer"},
    )
    assert create_response.status_code == 200
    client.post("/api/auth/logout")

    login_response = client.post("/api/auth/login", json={"username": "engineer-one", "password": "engineerpass123"})
    assert login_response.status_code == 200

    response = client.get("/api/update/status")

    assert response.status_code == 403


def test_update_install_conflict_is_reported(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    bootstrap(client)

    def fake_start(*_args, **_kwargs) -> update_manager.UpdateJobStatus:
        raise update_manager.HTTPException(status_code=409, detail="An update is already running")

    monkeypatch.setattr(update_manager, "start_update_job", fake_start)

    response = client.post("/api/update/install")

    assert response.status_code == 409
    assert "already running" in response.text


def test_update_install_returns_running_job_after_helper_launch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    bootstrap(client)
    update_script = tmp_path / "update-ubuntu.sh"
    update_script.write_text("#!/usr/bin/env bash\n")
    monkeypatch.setattr(settings, "update_script_path", update_script)
    monkeypatch.setattr(update_manager, "_latest_commit", lambda: "bbbb222")
    monkeypatch.setattr(update_manager, "request_helper", lambda *_args, **_kwargs: {"pid": os.getpid()})

    response = client.post("/api/update/install")

    assert response.status_code == 200
    assert response.json()["job_status"] == "running"
    assert response.json()["latest_commit"] == "bbbb222"


def test_update_pid_permission_denied_still_means_process_exists(monkeypatch: pytest.MonkeyPatch):
    def permission_denied(_pid: int, _signal: int) -> None:
        raise PermissionError

    monkeypatch.setattr(update_manager.os, "kill", permission_denied)

    assert update_manager._pid_running(os.getpid()) is True


def test_owner_can_launch_updater(client: TestClient):
    bootstrap(client)

    response = client.post("/api/update/launch", headers={"host": "192.168.7.239:5173"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["updater_url"].startswith("http://192.168.7.239:5174/?token=")
    assert payload["expires_at"]


def test_updater_launch_uses_forwarded_public_origin(client: TestClient):
    bootstrap(client)

    response = client.post(
        "/api/update/launch",
        headers={
            "host": "127.0.0.1:8000",
            "x-forwarded-host": "easysrt.example.com:443",
            "x-forwarded-proto": "https",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updater_url"].startswith("https://easysrt.example.com:5174/?token=")


def test_updater_requires_token(updater_client: TestClient):
    response = updater_client.get("/api/update/status")

    assert response.status_code == 422


def test_updater_accepts_valid_handoff(monkeypatch: pytest.MonkeyPatch, updater_client: TestClient):
    launch = create_launch_response(
        updater_client.build_request(
            "POST",
            "/api/update/launch",
            headers={"host": "192.168.7.239:5173"},
        ),
        User(id="owner-id", username="owner", password_hash="x", role=UserRole.OWNER),
    )
    token = launch.updater_url.split("token=", 1)[1]

    monkeypatch.setattr(
        update_manager,
        "get_update_status",
        lambda: update_manager.UpdateStatus(
            repo_url="https://github.com/JustSo-Technology/JustSo.EasySRT.git",
            repo_ref="main",
            installed_commit="aaaa111",
            latest_commit="bbbb222",
            update_available=True,
            checked_at="2026-03-18T00:00:00+00:00",
            job_status="idle",
            current_step=None,
            log_lines=[],
            error=None,
            backup_path=None,
            stash_ref=None,
            rollback_succeeded=None,
            sender_impact="none_expected",
            sender_message="This update runs through the local host control helper. It restarts the control plane only, and the live sender is not restarted automatically.",
        ),
    )

    exchanged = updater_client.post("/api/update/session", headers={"X-Updater-Token": token})
    assert exchanged.status_code == 200
    response = updater_client.get("/api/update/status", headers={"X-Updater-Token": exchanged.json()["token"]})

    assert response.status_code == 200
    assert response.json()["update_available"] is True


def test_redundancy_status_defaults_to_unprotected_single_node(client: TestClient):
    bootstrap(client)

    response = client.get("/api/redundancy/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "single_node"
    assert payload["product_state"] == "unprotected"
    assert payload["config_sync_status"] == "not_applicable"
    assert payload["source"] == "default"
    assert payload["nodes"][0]["role"] == "live"
    assert payload["nodes"][0]["stream_authority"] is True


def test_redundancy_status_reads_state_file(client: TestClient):
    bootstrap(client)
    settings.redundancy_state_path.write_text(
        json.dumps(
            {
                "mode": "partner_redundancy",
                "product_state": "degraded_protection",
                "product_state_reason": "Standby config is behind.",
                "live_node_id": "node-a",
                "live_node_label": "Sydney",
                "standby_node_id": "node-b",
                "standby_node_label": "Melbourne",
                "output_status": "healthy",
                "output_status_reason": "Usable media confirmed recently.",
                "config_sync_status": "behind",
                "config_sync_reason": "Partner has not acknowledged the latest config version.",
                "partner_takeover_ready": False,
                "last_action": "Config sync delayed",
                "nodes": [
                    {
                        "id": "node-a",
                        "label": "Sydney",
                        "role": "live",
                        "connection_state": "online",
                        "stream_authority": True,
                        "config_authority": True,
                        "runtime_status": "healthy",
                        "sync_status": "up_to_date",
                        "takeover_ready": False,
                    },
                    {
                        "id": "node-b",
                        "label": "Melbourne",
                        "role": "standby",
                        "connection_state": "online",
                        "stream_authority": False,
                        "config_authority": False,
                        "runtime_status": "valid",
                        "sync_status": "behind",
                        "takeover_ready": False,
                    },
                ],
            }
        )
    )

    response = client.get("/api/redundancy/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product_state"] == "degraded_protection"
    assert payload["live_node_label"] == "Sydney"
    assert payload["standby_node_label"] == "Melbourne"
    assert payload["config_sync_status"] == "behind"
    assert payload["source"] == "state_file"


def test_replicated_config_status_initializes_with_local_authority(client: TestClient):
    bootstrap(client)

    response = client.get("/api/redundancy/config-sync")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_version"] == 1
    assert payload["partner_sync_state"] == "not_configured"
    assert payload["takeover_eligibility"] == "unknown"
    assert payload["authority_node_id"]


def test_partner_ack_marks_partner_takeover_ready(client: TestClient):
    bootstrap(client)

    response = client.post(
        "/api/redundancy/partner-ack",
        json={
            "partner_node_id": "node-b",
            "partner_node_label": "Melbourne",
            "acked_version": 1,
            "runtime_validation_state": "valid",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["partner_node_id"] == "node-b"
    assert payload["partner_sync_state"] == "up_to_date"
    assert payload["takeover_eligibility"] == "eligible"
    assert payload["last_acked_version"] == 1


def test_config_change_advances_version_and_invalidates_partner_readiness(client: TestClient):
    bootstrap(client)
    ack_response = client.post(
        "/api/redundancy/partner-ack",
        json={
            "partner_node_id": "node-b",
            "partner_node_label": "Melbourne",
            "acked_version": 1,
            "runtime_validation_state": "valid",
        },
    )
    assert ack_response.status_code == 200

    bundle = load_bundle()
    payload = bundle.site.model_dump()
    payload["profile"]["mux_rate_kbps"] = bundle.site.profile.mux_rate_kbps + 100

    update_response = client.put("/api/config/site", json=payload)

    assert update_response.status_code == 200

    status_response = client.get("/api/redundancy/config-sync")

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["current_version"] == 2
    assert status_payload["last_acked_version"] == 1
    assert status_payload["partner_sync_state"] == "awaiting_ack"
    assert status_payload["takeover_eligibility"] == "ineligible_config_behind"


@pytest.mark.parametrize("role", ["operator", "owner"])
def test_bootstrap_always_creates_owner(client: TestClient, role: str):
    response = client.post("/api/auth/bootstrap-owner", json={"username": "first", "password": "supersecurepass", "role": role})
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "owner"


def test_concurrent_bootstrap_creates_only_one_owner():
    from concurrent.futures import ThreadPoolExecutor
    from sqlmodel import Session, select
    from app.core.db import get_engine

    def create(username):
        with TestClient(app) as test_client:
            return test_client.post("/api/auth/bootstrap-owner", json={"username": username, "password": "supersecurepass", "role": "operator"}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(create, ["first", "second"]))
    assert sorted(statuses) == [200, 409]
    with Session(get_engine()) as session:
        users = session.exec(select(User)).all()
        assert len(users) == 1
        assert users[0].role == UserRole.OWNER


def test_rejected_duplicate_config_has_no_persisted_side_effects(client: TestClient):
    bootstrap(client)
    payload = {"name": "Shared Route", "site": load_bundle().site.model_dump()}
    assert client.post("/api/config/saved", json=payload).status_code == 200
    before_config = client.get("/api/config").json()
    before_saved = client.get("/api/config/saved").json()
    paths = [settings.app_config_path, settings.site_config_path, settings.runtime_config_path, settings.sender_env_path]
    before_files = {path: path.read_bytes() for path in paths}
    payload["site"]["destination"]["host"] = "changed.example.com"
    response = client.post("/api/config/saved", json=payload)
    assert response.status_code == 409
    assert client.get("/api/config").json() == before_config
    assert client.get("/api/config/saved").json() == before_saved
    assert {path: path.read_bytes() for path in paths} == before_files


@pytest.mark.parametrize("origin", ["https://easysrt.example.com", "https://easysrt.example.com:8443", "https://[2001:db8::1]"])
def test_updater_return_preserves_configured_public_origin(monkeypatch, updater_client, origin):
    from app.services.update_handoff import decode_handoff_token
    monkeypatch.setattr(settings, "frontend_origin", origin)
    launch = create_launch_response(updater_client.build_request("POST", "/api/update/launch"), User(username="owner", password_hash="x", role=UserRole.OWNER))
    claims = decode_handoff_token(launch.updater_url.split("token=", 1)[1])
    assert claims["return_url"] == origin + "/"


def test_updater_session_survives_handoff_expiry_but_is_bounded(monkeypatch, updater_client):
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    from app.services import update_handoff
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    monkeypatch.setattr(update_handoff, "_now", lambda: now)
    launch = create_launch_response(updater_client.build_request("POST", "/api/update/launch"), User(username="owner", password_hash="x", role=UserRole.OWNER))
    handoff = launch.updater_url.split("token=", 1)[1]
    response = updater_client.post("/api/update/session", headers={"X-Updater-Token": handoff})
    assert response.status_code == 200
    token = response.json()["token"]
    monkeypatch.setattr(update_manager, "get_update_job", lambda: {"job_status": "running"})
    now += timedelta(minutes=20)
    assert updater_client.get("/api/update/job", headers={"X-Updater-Token": token}).status_code == 200
    assert updater_client.post("/api/update/session", headers={"X-Updater-Token": handoff}).status_code == 401
    # A session cannot mint another session, and cannot authorize the main app.
    assert updater_client.post("/api/update/session", headers={"X-Updater-Token": token}).status_code == 401
    with pytest.raises(HTTPException):
        update_handoff.decode_handoff_token(token)
    now += timedelta(seconds=settings.updater_session_ttl_seconds)
    assert updater_client.get("/api/update/job", headers={"X-Updater-Token": token}).status_code == 401


@pytest.mark.parametrize("ref,output,expected", [
    ("main", "abc refs/heads/main\n", "abc"),
    ("v1.0", "abc refs/tags/v1.0\n", "abc"),
    ("v1.0", "tagobject refs/tags/v1.0\nabc refs/tags/v1.0^{}\n", "abc"),
    ("refs/tags/v1.0", "tagobject refs/tags/v1.0\nabc refs/tags/v1.0^{}\n", "abc"),
])
def test_update_discovery_resolves_branches_and_tags(monkeypatch, ref, output, expected):
    monkeypatch.setattr(settings, "update_repo_ref", ref)
    def fake_git(*args):
        assert args[0] == "ls-remote"
        assert "--heads" not in args
        assert (ref if ref.startswith("refs/") else "refs/tags/" + ref) in args
        return CompletedProcess(args, 0, stdout=output, stderr="")
    monkeypatch.setattr(update_manager, "_run_git", fake_git)
    assert update_manager._latest_commit() == expected


def test_update_discovery_rejects_ambiguous_ref(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(settings, "update_repo_ref", "same")
    monkeypatch.setattr(update_manager, "_run_git", lambda *args: CompletedProcess(args, 0, stdout="abc refs/heads/same\ndef refs/tags/same\n", stderr=""))
    with pytest.raises(HTTPException, match="Ambiguous ref"):
        update_manager._latest_commit()
