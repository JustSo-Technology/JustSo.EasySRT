import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import shlex
import tempfile
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.core.settings import settings
from app.models.site_config import SavedDestinationRecord, SavedInputRecord, SavedSiteConfigRecord, SiteConfigState
from app.schemas.config import (
    AppConfig,
    ConfigBundle,
    Destination,
    InputSource,
    RuntimeConfig,
    SavedDestinationEntry,
    SavedInputEntry,
    SavedSiteConfigSummary,
    SiteConfig,
    StreamProfile,
)


DEFAULT_APP = AppConfig()
DEFAULT_SITE = SiteConfig(
    input=InputSource(name="demo-input", url="http://localhost:8000/demo.mp3"),
    destination=Destination(name="demo-destination", protocol="srt", host="127.0.0.1", port=16466),
    profile=StreamProfile(name="broadcast-standard"),
)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _write_sender_env(path: Path, ffmpeg_command: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, f"FFMPEG_CMD={shlex.quote(ffmpeg_command)}\n")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def build_runtime_config(app_config: AppConfig, site_config: SiteConfig) -> RuntimeConfig:
    profile = site_config.profile
    destination = site_config.destination
    scheme = urlsplit(site_config.input.url).scheme
    policy = settings.recovery
    if site_config.destination.protocol == "srt" and profile.srt_latency_ms / 1000 >= min(
        policy.startup_seconds, policy.output_stall_seconds, policy.io_timeout_seconds
    ):
        raise ValueError("SRT latency must be shorter than recovery startup, output-stall and I/O timeouts")
    args = [settings.ffmpeg_binary, "-re"]
    if scheme != "file":
        args.extend(["-rw_timeout", str(int(policy.io_timeout_seconds * 1_000_000))])
    args.extend(["-i", site_config.input.url])
    if profile.enable_video:
        if profile.video_source == "black_test_frames":
            args.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=black:s={profile.video_resolution}:r={profile.video_frame_rate}",
                    "-map",
                    "0:a:0",
                    "-map",
                    "1:v:0",
                    "-c:a",
                    "mp2",
                    "-b:a",
                    f"{profile.audio_bitrate_kbps}k",
                    "-ar",
                    str(profile.sample_rate_hz),
                    "-ac",
                    str(profile.channels),
                    "-c:v",
                    profile.video_codec,
                    "-b:v",
                    f"{profile.video_bitrate_kbps}k",
                    "-r",
                    str(profile.video_frame_rate),
                    "-s",
                    profile.video_resolution,
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
        else:
            args.append("-vn")
    else:
        args.append("-vn")
    if "-c:a" not in args:
        args.extend(
            [
                "-c:a",
                "mp2",
                "-b:a",
                f"{profile.audio_bitrate_kbps}k",
                "-ar",
                str(profile.sample_rate_hz),
                "-ac",
                str(profile.channels),
            ]
        )
    args.extend(
        [
            "-shortest",
            "-flush_packets",
            "1",
            "-f",
            "mpegts",
            "-muxrate",
            f"{profile.mux_rate_kbps}k",
            "-pcr_period",
            str(profile.pcr_period_ms),
        ]
    )
    args.extend(["-rw_timeout", str(int(policy.io_timeout_seconds * 1_000_000)),
                 _destination_url(destination, profile.srt_latency_ms, profile.mux_rate_kbps)])
    ffmpeg_command = shlex.join(args)
    summary = {"input": site_config.input.name, "destination": destination.name,
               "endpoint": f"{destination.protocol}://{_format_host_for_url(destination.host)}:{destination.port}",
               "profile": profile.name}
    config_id = hashlib.sha256(json.dumps({"args": args, "policy": policy.model_dump(), "summary": summary}, sort_keys=True).encode()).hexdigest()
    return RuntimeConfig(
        ffmpeg_command=ffmpeg_command,
        service_name=settings.sender_service_name,
        generated_from_station=app_config.station_name,
        sender_env_path=str(settings.sender_env_path.resolve()),
        ffmpeg_args=args,
        input_scheme=scheme,
        recovery=policy,
        config_id=config_id,
        summary=summary,
    )


def _destination_url(destination: Destination, latency_ms: int, mux_rate_kbps: int = 600) -> str:
    endpoint = _format_host_for_url(destination.host)
    if destination.protocol == "udp":
        return f"udp://{endpoint}:{destination.port}"
    # Bound queued media and let sustained backpressure surface as a blocked
    # write instead of silently discarding late packets indefinitely.
    send_buffer = max(262144, int(mux_rate_kbps * 125 * max(1, latency_ms / 500)))
    return f"srt://{endpoint}:{destination.port}?mode=caller&latency={latency_ms * 1000}&sndbuf={send_buffer}&tlpktdrop=0"


def _format_host_for_url(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def load_persisted_runtime_config() -> RuntimeConfig | None:
    from app.services.config_snapshots import read_selected
    selected = read_selected()
    if selected:
        return selected.runtime
    runtime_payload = _read_json(settings.runtime_config_path)
    if not runtime_payload:
        return None
    return RuntimeConfig.model_validate(runtime_payload)


def load_legacy_bundle() -> ConfigBundle:
    app_config = AppConfig.model_validate(_read_json(settings.app_config_path) or DEFAULT_APP.model_dump())
    site_config = SiteConfig.model_validate(_read_json(settings.site_config_path) or DEFAULT_SITE.model_dump())
    runtime = build_runtime_config(app_config, site_config)
    return ConfigBundle(app=app_config, site=site_config, runtime=runtime)


def load_bundle() -> ConfigBundle:
    from app.services.config_snapshots import read_selected
    return read_selected() or load_legacy_bundle()


def save_bundle(app_config: AppConfig, site_config: SiteConfig) -> ConfigBundle:
    try:
        runtime = build_runtime_config(app_config, site_config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _write_json(settings.app_config_path, app_config.model_dump())
    _write_json(settings.site_config_path, site_config.model_dump())
    _write_json(settings.runtime_config_path, runtime.model_dump())
    _write_sender_env(settings.sender_env_path, runtime.ffmpeg_command)
    return ConfigBundle(app=app_config, site=site_config, runtime=runtime)


def migrate_legacy_runtime() -> None:
    """Refresh legacy candidates or changed host policy, never an applied run."""
    from app.services.config_snapshots import read_selected
    if read_selected():
        return
    try:
        payload = _read_json(settings.runtime_config_path)
        if isinstance(payload, dict) and payload.get("ffmpeg_command") and (
            "ffmpeg_args" not in payload or payload.get("recovery") != settings.recovery.model_dump()
        ):
            bundle = load_bundle()
            save_bundle(bundle.app, bundle.site)
    except (OSError, ValueError, HTTPException):
        # Leave malformed candidates for diagnostics/preflight; keep the API
        # available and never attempt to repair an active process implicitly.
        return


def _saved_config_summary(record: SavedSiteConfigRecord) -> SavedSiteConfigSummary:
    return SavedSiteConfigSummary(id=record.id, name=record.name, revision=record.revision,
                                  created_at=record.created_at, updated_at=record.updated_at)


def get_preset(session: Session, preset_id: str) -> SavedSiteConfigRecord:
    record = session.get(SavedSiteConfigRecord, preset_id)
    if record is None:
        raise HTTPException(404, "Preset not found")
    return record


def check_revision(record: SavedSiteConfigRecord, expected: int | None):
    if expected is None:
        raise HTTPException(428, "Expected preset revision is required; open the preset again")
    if record.revision != expected:
        raise HTTPException(409, "Preset changed; open and review it again before saving or applying")


def list_saved_site_configs(session: Session) -> list[SavedSiteConfigSummary]:
    records = session.exec(select(SavedSiteConfigRecord).order_by(SavedSiteConfigRecord.updated_at.desc())).all()
    return [_saved_config_summary(record) for record in records]


def save_named_site_config(session: Session, name: str, site_config: SiteConfig,
                           created_by_user_id: str | None = None):
    normalized_name = name.strip()
    existing = session.exec(select(SavedSiteConfigRecord).where(SavedSiteConfigRecord.name == normalized_name)).first()
    if existing:
        raise HTTPException(409, "A preset with that name already exists; open it before overwriting")
    record = SavedSiteConfigRecord(name=normalized_name, site_payload=site_config.model_dump_json(),
                                   created_by_user_id=created_by_user_id)
    session.add(record)
    session.flush()
    return _saved_config_summary(record)


def update_saved_site_config(session: Session, preset_id: str, site: SiteConfig, expected_revision: int | None):
    record = get_preset(session, preset_id)
    check_revision(record, expected_revision)
    record.site_payload = site.model_dump_json()
    record.revision += 1
    record.updated_at = datetime.now(timezone.utc)
    session.add(record)
    session.flush()
    return _saved_config_summary(record)


def rename_saved_site_config(session: Session, preset_id: str, name: str, expected_revision: int | None):
    record = get_preset(session, preset_id)
    check_revision(record, expected_revision)
    name = name.strip()
    existing = session.exec(select(SavedSiteConfigRecord).where(SavedSiteConfigRecord.name == name)).first()
    if existing and existing.id != record.id:
        raise HTTPException(409, "A preset with that name already exists")
    record.name = name
    record.revision += 1
    record.updated_at = datetime.now(timezone.utc)
    session.add(record)
    session.flush()
    return _saved_config_summary(record)


def delete_saved_site_config(session: Session, preset_id: str, expected_revision: int | None):
    record = get_preset(session, preset_id)
    check_revision(record, expected_revision)
    state = session.get(SiteConfigState, "default")
    if state and state.active_saved_config_id == record.id:
        state.active_saved_config_id = None
        session.add(state)
    session.delete(record)
    session.flush()


def preview_preset(session: Session, preset_id: str, expected_revision: int | None = None):
    from app.schemas.config import SavedSiteConfigDetail
    from app.services.config_snapshots import digest, read_app_settings
    record = get_preset(session, preset_id)
    if expected_revision is not None:
        check_revision(record, expected_revision)
    app = read_app_settings()
    site = SiteConfig.model_validate_json(record.site_payload)
    try:
        runtime = build_runtime_config(app, site)
    except ValueError:
        raise HTTPException(422, "Preset is incompatible with current sender settings") from None
    selected = load_bundle().selected
    return SavedSiteConfigDetail(saved_config=_saved_config_summary(record),
        bundle=ConfigBundle(app=app, site=site, runtime=runtime), app_digest=digest(app.model_dump()),
        runtime_digest=digest(runtime.model_dump()), expected_selection_id=selected.id if selected else None)


def list_saved_inputs(session: Session) -> list[SavedInputEntry]:
    records = session.exec(select(SavedInputRecord).order_by(SavedInputRecord.updated_at.desc())).all()
    entries: list[SavedInputEntry] = []
    for record in records:
        payload = InputSource.model_validate(json.loads(record.input_payload))
        entries.append(
            SavedInputEntry(
                id=record.id,
                name=payload.name,
                url=payload.url,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
    return entries


def save_input(session: Session, input_source: InputSource) -> SavedInputEntry:
    existing = session.exec(select(SavedInputRecord).where(SavedInputRecord.name == input_source.name.strip())).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A saved input with that name already exists")
    now = datetime.now(timezone.utc)
    record = SavedInputRecord(name=input_source.name.strip(), input_payload=json.dumps(input_source.model_dump()), created_at=now, updated_at=now)
    session.add(record)
    session.commit()
    session.refresh(record)
    return SavedInputEntry(id=record.id, name=input_source.name, url=input_source.url, created_at=record.created_at, updated_at=record.updated_at)


def list_saved_destinations(session: Session) -> list[SavedDestinationEntry]:
    records = session.exec(select(SavedDestinationRecord).order_by(SavedDestinationRecord.updated_at.desc())).all()
    entries: list[SavedDestinationEntry] = []
    for record in records:
        payload = Destination.model_validate(json.loads(record.destination_payload))
        entries.append(
            SavedDestinationEntry(
                id=record.id,
                name=payload.name,
                protocol=payload.protocol,
                host=payload.host,
                port=payload.port,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
    return entries


def save_destination(session: Session, destination: Destination) -> SavedDestinationEntry:
    existing = session.exec(select(SavedDestinationRecord).where(SavedDestinationRecord.name == destination.name.strip())).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A saved destination with that name already exists")
    now = datetime.now(timezone.utc)
    record = SavedDestinationRecord(
        name=destination.name.strip(),
        destination_payload=json.dumps(destination.model_dump()),
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return SavedDestinationEntry(
        id=record.id,
        name=destination.name,
        protocol=destination.protocol,
        host=destination.host,
        port=destination.port,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
