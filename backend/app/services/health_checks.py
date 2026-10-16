import json
import shlex
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app.core.settings import settings
from app.schemas.config import ConfigBundle, RuntimeConfig
from app.schemas.system import DiagnosticCheck
from app.services.config_service import build_runtime_config, load_bundle, load_persisted_runtime_config


def _make_check(
    *,
    name: str,
    ok: bool,
    detail: str,
    severity: str,
    category: str,
    blocking: bool,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        name=name,
        ok=ok,
        detail=detail,
        severity=severity,
        category=category,
        blocking=blocking,
    )


def _check_error(name: str, category: str, detail: str, blocking: bool = True) -> DiagnosticCheck:
    return _make_check(
        name=name,
        ok=False,
        detail=detail,
        severity="critical" if blocking else "warning",
        category=category,
        blocking=blocking,
    )


def _resolve_privileged_command(binary_name: str) -> list[str] | None:
    binary = shutil.which(binary_name)
    if binary is None:
        return None
    return [binary]


def _run_command(command: list[str], *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run([*command, *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([*command, *args], 1, stdout="", stderr=str(exc))


def check_config_validity() -> tuple[DiagnosticCheck, ConfigBundle | None]:
    try:
        bundle = load_bundle()
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return _check_error("config-valid", "runtime", f"Config invalid: {exc}"), None
    return (
        _make_check(
            name="config-valid",
            ok=True,
            detail="App and site config loaded successfully",
            severity="info",
            category="runtime",
            blocking=True,
        ),
        bundle,
    )


def check_ffmpeg_available() -> DiagnosticCheck:
    ffmpeg_path = shutil.which(settings.ffmpeg_binary)
    if ffmpeg_path is None:
        return _check_error("ffmpeg-binary", "system", f"{settings.ffmpeg_binary} not found")
    return _make_check(
        name="ffmpeg-binary",
        ok=True,
        detail=ffmpeg_path,
        severity="info",
        category="system",
        blocking=True,
    )


def check_ffmpeg_version() -> DiagnosticCheck:
    ffmpeg_path = shutil.which(settings.ffmpeg_binary)
    if ffmpeg_path is None:
        return _check_error("ffmpeg-version", "system", f"{settings.ffmpeg_binary} not found")
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _check_error("ffmpeg-version", "system", f"Unable to read ffmpeg version: {exc}")
    version_line = (result.stdout or result.stderr).splitlines()
    detail = version_line[0] if version_line else "No ffmpeg version output"
    return _make_check(
        name="ffmpeg-version",
        ok=result.returncode == 0,
        detail=detail,
        severity="info" if result.returncode == 0 else "warning",
        category="system",
        blocking=True,
    )


def check_runtime_config_health(bundle: ConfigBundle | None = None) -> DiagnosticCheck:
    try:
        persisted_runtime = load_persisted_runtime_config()
    except ValidationError as exc:
        return _check_error("runtime-config", "runtime", f"runtime_config.json is invalid: {exc}")
    if persisted_runtime is None:
        return _check_error("runtime-config", "runtime", "runtime_config.json is missing")
    bundle = bundle or load_bundle()
    expected = build_runtime_config(bundle.app, bundle.site)
    if persisted_runtime != expected:
        return _check_error("runtime-config", "runtime", "runtime_config.json does not match derived runtime")
    return _make_check(
        name="runtime-config",
        ok=True,
        detail=str(settings.runtime_config_path.resolve()),
        severity="info",
        category="runtime",
        blocking=True,
    )


def check_sender_env_health(expected_runtime: RuntimeConfig | None = None) -> DiagnosticCheck:
    expected_runtime = expected_runtime or load_bundle().runtime
    env_path = settings.sender_env_path
    if not env_path.exists():
        return _check_error("sender-env", "runtime", "sender.env is missing")
    env_text = env_path.read_text()
    expected_line = f"FFMPEG_CMD={shlex.quote(expected_runtime.ffmpeg_command)}"
    if "FFMPEG_CMD=" not in env_text:
        return _check_error("sender-env", "runtime", "sender.env is missing FFMPEG_CMD")
    if expected_line not in env_text:
        return _check_error("sender-env", "runtime", "sender.env does not match the derived runtime command")
    return _make_check(
        name="sender-env",
        ok=True,
        detail=str(env_path.resolve()),
        severity="info",
        category="runtime",
        blocking=True,
    )


def check_service_unit_configured() -> DiagnosticCheck:
    if not settings.sender_service_name.strip():
        return _check_error("service-name", "service", "Sender service name is not configured")
    return _make_check(
        name="service-name",
        ok=True,
        detail=settings.sender_service_name,
        severity="info",
        category="service",
        blocking=True,
    )


def check_service_unit_installed() -> DiagnosticCheck:
    systemctl_command = _resolve_privileged_command("systemctl")
    if systemctl_command is None:
        return _check_error("service-unit-installed", "service", "systemctl not available in this environment")

    result = _run_command(
        systemctl_command,
        "show",
        settings.sender_service_name,
        "--property=LoadState",
        "--property=FragmentPath",
        "--value",
    )
    output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    load_state = output_lines[0] if output_lines else ""
    fragment_path = output_lines[1] if len(output_lines) > 1 else ""

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"Unable to inspect {settings.sender_service_name}"
        return _check_error("service-unit-installed", "service", detail)

    if load_state != "loaded":
        detail = f"{settings.sender_service_name} load state is {load_state or 'unknown'}"
        return _check_error("service-unit-installed", "service", detail)

    return _make_check(
        name="service-unit-installed",
        ok=True,
        detail=fragment_path or f"{settings.sender_service_name} is installed",
        severity="info",
        category="service",
        blocking=True,
    )


def check_sender_service_state() -> DiagnosticCheck:
    systemctl_command = _resolve_privileged_command("systemctl")
    if systemctl_command is None:
        return _make_check(
            name="sender-service-state",
            ok=False,
            detail="systemctl not available in this environment",
            severity="warning",
            category="service",
            blocking=False,
        )

    result = _run_command(systemctl_command, "is-active", settings.sender_service_name)
    state = result.stdout.strip() or result.stderr.strip() or "unknown"
    if state == "active":
        return _make_check(
            name="sender-service-state",
            ok=True,
            detail=f"{settings.sender_service_name} is active",
            severity="info",
            category="service",
            blocking=False,
        )

    severity = "critical" if state == "failed" else "warning"
    detail = state if result.returncode == 0 or result.stdout.strip() else f"{settings.sender_service_name}: {state}"
    return _make_check(
        name="sender-service-state",
        ok=False,
        detail=detail,
        severity=severity,
        category="service",
        blocking=False,
    )


def check_input_reachability(bundle: ConfigBundle | None = None) -> DiagnosticCheck:
    bundle = bundle or load_bundle()
    parsed = urlparse(bundle.site.input.url)
    scheme = parsed.scheme
    if scheme in {"http", "https"}:
        head_request = Request(bundle.site.input.url, method="HEAD")
        get_request = Request(bundle.site.input.url, method="GET")
        try:
            with urlopen(head_request, timeout=5) as response:
                return _make_check(
                    name="input-reachability",
                    ok=response.status < 400,
                    detail=f"HEAD {response.status}",
                    severity="info",
                    category="input",
                    blocking=False,
                )
        except (HTTPError, URLError) as head_exc:
            try:
                with urlopen(get_request, timeout=5) as response:
                    return _make_check(
                        name="input-reachability",
                        ok=response.status < 400,
                        detail=f"GET {response.status} after HEAD fallback",
                        severity="info",
                        category="input",
                        blocking=False,
                    )
            except (HTTPError, URLError) as exc:
                if isinstance(head_exc, HTTPError):
                    head_detail = f"HEAD failed with HTTP {head_exc.code}"
                else:
                    head_detail = f"HEAD failed: {head_exc}"
                return _make_check(
                    name="input-reachability",
                    ok=False,
                    detail=f"{head_detail}; GET failed: {exc}",
                    severity="warning",
                    category="input",
                    blocking=False,
                )
    if scheme == "file":
        file_path = Path(parsed.path)
        return _make_check(
            name="input-reachability",
            ok=file_path.exists(),
            detail=str(file_path),
            severity="info" if file_path.exists() else "warning",
            category="input",
            blocking=False,
        )
    return _make_check(
        name="input-reachability",
        ok=True,
        detail=f"{scheme} input accepted without active probe",
        severity="info",
        category="input",
        blocking=False,
    )


def check_destination_health(bundle: ConfigBundle | None = None) -> DiagnosticCheck:
    bundle = bundle or load_bundle()
    protocol = bundle.site.destination.protocol
    host = bundle.site.destination.host
    port = bundle.site.destination.port
    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    except socket.gaierror as exc:
        return _make_check(
            name="destination-health",
            ok=False,
            detail=f"{protocol.upper()} destination resolution failed: {exc}",
            severity="warning",
            category="output",
            blocking=False,
        )

    family, socktype, proto, _, sockaddr = addrinfo[0]
    try:
        with socket.socket(family, socktype, proto) as sock:
            sock.settimeout(2)
            sock.connect(sockaddr)
            sock.send(b"")
    except OSError as exc:
        return _make_check(
            name="destination-health",
            ok=False,
            detail=f"{protocol.upper()} destination precheck failed: {exc}",
            severity="warning",
            category="output",
            blocking=False,
        )

    return _make_check(
        name="destination-health",
        ok=True,
        detail=f"{protocol}://{host}:{port} resolved and accepted datagram precheck",
        severity="info",
        category="output",
        blocking=False,
    )


def collect_preflight_checks() -> list[DiagnosticCheck]:
    config_check, bundle = check_config_validity()
    checks = [config_check, check_ffmpeg_available(), check_service_unit_configured(), check_service_unit_installed()]
    if bundle is not None:
        checks.append(check_runtime_config_health(bundle))
        checks.append(check_sender_env_health(bundle.runtime))
    return checks


def collect_diagnostics_checks() -> list[DiagnosticCheck]:
    config_check, bundle = check_config_validity()
    checks = [
        config_check,
        check_ffmpeg_available(),
        check_ffmpeg_version(),
        check_service_unit_configured(),
        check_service_unit_installed(),
        check_sender_service_state(),
    ]
    if bundle is not None:
        checks.extend(
            [
                check_runtime_config_health(bundle),
                check_sender_env_health(bundle.runtime),
                check_input_reachability(bundle),
                check_destination_health(bundle),
            ]
        )
    return checks
