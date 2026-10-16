import json
from datetime import datetime, timezone
from pathlib import Path
import shlex
import tempfile

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
    args = [
        settings.ffmpeg_binary,
        "-re",
        "-i",
        site_config.input.url,
    ]
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
            "-f",
            "mpegts",
            "-muxrate",
            f"{profile.mux_rate_kbps}k",
            "-pcr_period",
            str(profile.pcr_period_ms),
            _destination_url(destination, profile.srt_latency_ms),
        ]
    )
    ffmpeg_command = shlex.join(args)
    return RuntimeConfig(
        ffmpeg_command=ffmpeg_command,
        service_name=settings.sender_service_name,
        generated_from_station=app_config.station_name,
        sender_env_path=str(settings.sender_env_path.resolve()),
    )


def _destination_url(destination: Destination, latency_ms: int) -> str:
    endpoint = _format_host_for_url(destination.host)
    if destination.protocol == "udp":
        return f"udp://{endpoint}:{destination.port}"
    return f"srt://{endpoint}:{destination.port}?mode=caller&latency={latency_ms * 1000}"


def _format_host_for_url(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def load_persisted_runtime_config() -> RuntimeConfig | None:
    runtime_payload = _read_json(settings.runtime_config_path)
    if not runtime_payload:
        return None
    return RuntimeConfig.model_validate(runtime_payload)


def load_bundle() -> ConfigBundle:
    app_config = AppConfig.model_validate(_read_json(settings.app_config_path) or DEFAULT_APP.model_dump())
    site_config = SiteConfig.model_validate(_read_json(settings.site_config_path) or DEFAULT_SITE.model_dump())
    runtime = build_runtime_config(app_config, site_config)
    return ConfigBundle(app=app_config, site=site_config, runtime=runtime)


def save_bundle(app_config: AppConfig, site_config: SiteConfig) -> ConfigBundle:
    runtime = build_runtime_config(app_config, site_config)
    _write_json(settings.app_config_path, app_config.model_dump())
    _write_json(settings.site_config_path, site_config.model_dump())
    _write_json(settings.runtime_config_path, runtime.model_dump())
    _write_sender_env(settings.sender_env_path, runtime.ffmpeg_command)
    return ConfigBundle(app=app_config, site=site_config, runtime=runtime)


def _saved_config_summary(record: SavedSiteConfigRecord, is_active: bool = False) -> SavedSiteConfigSummary:
    return SavedSiteConfigSummary(
        id=record.id,
        name=record.name,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_loaded_at=record.last_loaded_at,
        is_active=is_active,
    )


def _get_or_create_site_config_state(session: Session) -> SiteConfigState:
    state = session.get(SiteConfigState, "default")
    if state is None:
        state = SiteConfigState()
        session.add(state)
        session.flush()
        session.refresh(state)
    return state


def list_saved_site_configs(session: Session) -> list[SavedSiteConfigSummary]:
    state = session.get(SiteConfigState, "default")
    records = session.exec(select(SavedSiteConfigRecord).order_by(SavedSiteConfigRecord.updated_at.desc())).all()
    return [_saved_config_summary(record, is_active=state is not None and record.id == state.active_saved_config_id) for record in records]


def save_named_site_config(
    session: Session,
    name: str,
    site_config: SiteConfig,
    app_config: AppConfig,
    created_by_user_id: str | None = None,
    overwrite: bool = False,
):
    normalized_name = name.strip()
    record = session.exec(select(SavedSiteConfigRecord).where(SavedSiteConfigRecord.name == normalized_name)).first()
    now = datetime.now(timezone.utc)
    if record is None:
        record = SavedSiteConfigRecord(
            name=normalized_name,
            site_payload=json.dumps(site_config.model_dump()),
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
    else:
        if not overwrite:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A saved config with that name already exists")
        record.site_payload = json.dumps(site_config.model_dump())
        record.updated_at = now
        if created_by_user_id is not None:
            record.created_by_user_id = created_by_user_id
    bundle = save_bundle(app_config, site_config)
    session.add(record)
    session.flush()
    session.refresh(record)
    state = _get_or_create_site_config_state(session)
    state.active_saved_config_id = record.id
    state.updated_at = now
    session.add(state)
    session.commit()
    return _saved_config_summary(record, is_active=True), bundle


def load_saved_site_config(session: Session, saved_config_id: str, app_config: AppConfig) -> ConfigBundle:
    record = session.get(SavedSiteConfigRecord, saved_config_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved config not found")
    site_config = SiteConfig.model_validate(json.loads(record.site_payload))
    bundle = save_bundle(app_config, site_config)
    now = datetime.now(timezone.utc)
    record.last_loaded_at = now
    session.add(record)
    state = _get_or_create_site_config_state(session)
    state.active_saved_config_id = record.id
    state.updated_at = now
    session.add(state)
    session.commit()
    return bundle


def rename_saved_site_config(session: Session, saved_config_id: str, name: str) -> SavedSiteConfigSummary:
    record = session.get(SavedSiteConfigRecord, saved_config_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved config not found")
    normalized_name = name.strip()
    existing = session.exec(select(SavedSiteConfigRecord).where(SavedSiteConfigRecord.name == normalized_name)).first()
    if existing is not None and existing.id != record.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A saved config with that name already exists")
    record.name = normalized_name
    record.updated_at = datetime.now(timezone.utc)
    session.add(record)
    session.commit()
    session.refresh(record)
    state = _get_or_create_site_config_state(session)
    return _saved_config_summary(record, is_active=record.id == state.active_saved_config_id)


def delete_saved_site_config(session: Session, saved_config_id: str) -> None:
    record = session.get(SavedSiteConfigRecord, saved_config_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved config not found")
    state = _get_or_create_site_config_state(session)
    if state.active_saved_config_id == record.id:
        state.active_saved_config_id = None
        state.updated_at = datetime.now(timezone.utc)
        session.add(state)
    session.delete(record)
    session.commit()


def clear_active_saved_site_config(session: Session) -> None:
    state = _get_or_create_site_config_state(session)
    if state.active_saved_config_id is not None:
        state.active_saved_config_id = None
        state.updated_at = datetime.now(timezone.utc)
        session.add(state)
        session.commit()


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
