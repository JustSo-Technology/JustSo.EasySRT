"""Immutable generations with SQLite as the durable publication journal.

A staged generation has no authority until SelectedConfigState commits. The
filesystem pointer is a projection: after any interrupted publication, restore
it from SQLite before readers or service commands proceed. Lock order is always
sender target lock, then SQLite writer. Library-only writers never take it.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import shlex
from pathlib import Path
import threading
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.db import get_engine
from app.core.settings import settings
from app.models.site_config import ConfigSnapshot, SelectedConfigState, SavedSiteConfigRecord, SiteConfigState
from app.schemas.config import AppConfig, ConfigBundle, SelectionSummary

_local = threading.local()


@contextmanager
def target_lock():
    path = settings.data_dir.resolve() / "config-control.lock"
    held = getattr(_local, "held", {})
    if path in held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        _local.held = {**held, path: handle}
        try:
            yield
        finally:
            _local.held = held
            fcntl.flock(handle, fcntl.LOCK_UN)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def durable_write(path: Path, content: str):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}")
    try:
        with open(temporary, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def sync_directory(path: Path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def generation_path(snapshot_id: str) -> Path:
    # IDs are generated here; still reject traversal at every file boundary.
    try:
        from uuid import UUID
        if str(UUID(snapshot_id)) != snapshot_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid snapshot identity") from None
    return settings.data_dir / "generations" / snapshot_id


def stage(snapshot: ConfigSnapshot):
    folder = generation_path(snapshot.id)
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    payload = json.loads(snapshot.bundle_payload)
    for name, value in {"bundle.json": payload, "site_config.json": payload["site"],
                        "app_config.json": payload["app"], "runtime_config.json": payload["runtime"]}.items():
        durable_write(folder / name, json.dumps(value, sort_keys=True) + "\n")
    durable_write(folder / "sender.env", f"FFMPEG_CMD={shlex.quote(payload['runtime']['ffmpeg_command'])}\n")
    sync_directory(folder)
    sync_directory(folder.parent)


def switch_pointer(snapshot_id: str | None):
    pointer = settings.data_dir / "selected"
    if snapshot_id is None:
        pointer.unlink(missing_ok=True)
        sync_directory(settings.data_dir)
        return
    target = Path("generations") / snapshot_id
    if pointer.is_symlink() and os.readlink(pointer) == str(target):
        return
    temporary = pointer.with_name(f".selected.{uuid4().hex}")
    try:
        temporary.symlink_to(target, target_is_directory=True)
        temporary.replace(pointer)
        sync_directory(pointer.parent)
    finally:
        temporary.unlink(missing_ok=True)


def summary(snapshot: ConfigSnapshot) -> SelectionSummary:
    return SelectionSummary(id=snapshot.id, source_preset_id=snapshot.source_preset_id,
                            source_revision=snapshot.source_revision, source_name=snapshot.source_name,
                            target=snapshot.target, created_at=snapshot.created_at)


def bundle_for(snapshot: ConfigSnapshot) -> ConfigBundle:
    bundle = ConfigBundle.model_validate_json(snapshot.bundle_payload)
    bundle.selected = summary(snapshot)
    return bundle


def recover(session: Session) -> ConfigSnapshot | None:
    state = session.get(SelectedConfigState, "default")
    snapshot = session.get(ConfigSnapshot, state.snapshot_id) if state else None
    if state and snapshot is None:
        raise HTTPException(503, "Selected configuration is unavailable; inspect the publication journal")
    if snapshot:
        # Restore interrupted filesystem publication from durable committed data.
        # Never trust a partially written/uncommitted generation.
        folder = generation_path(snapshot.id)
        try:
            valid = digest(json.loads((folder / "bundle.json").read_text())) == snapshot.digest
            for name, key in (("runtime_config.json", "runtime"), ("site_config.json", "site"), ("app_config.json", "app")):
                valid = valid and json.loads((folder / name).read_text()) == json.loads(snapshot.bundle_payload)[key]
            command = json.loads(snapshot.bundle_payload)["runtime"]["ffmpeg_command"]
            valid = valid and (folder / "sender.env").read_text() == f"FFMPEG_CMD={shlex.quote(command)}\n"
        except (OSError, ValueError):
            valid = False
        if not valid:
            stage(snapshot)
    switch_pointer(snapshot.id if snapshot else None)
    return snapshot


def read_selected() -> ConfigBundle | None:
    with target_lock(), Session(get_engine()) as session:
        snapshot = recover(session)
        return bundle_for(snapshot) if snapshot else None


def read_app_settings() -> AppConfig:
    from app.services.config_service import DEFAULT_APP, _read_json
    return AppConfig.model_validate(_read_json(settings.app_config_path) or DEFAULT_APP.model_dump())


def make_snapshot(bundle: ConfigBundle, **metadata) -> ConfigSnapshot:
    snapshot_id = str(uuid4())
    bundle = bundle.model_copy(deep=True)
    bundle.selected = None
    bundle.capabilities = []
    bundle.runtime.snapshot_id = snapshot_id
    payload = bundle.model_dump(mode="json")
    return ConfigSnapshot(id=snapshot_id, bundle_payload=json.dumps(payload), digest=digest(payload), **metadata)


def migrate_selection():
    """Capture disk state once; it is selection provenance, never live evidence."""
    from app.services.config_service import load_legacy_bundle
    with target_lock(), Session(get_engine()) as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if session.get(SelectedConfigState, "default"):
            recover(session)
            return
        if not settings.site_config_path.exists() and not settings.runtime_config_path.exists():
            recover(session)
            return
        try:
            bundle = load_legacy_bundle()
        except (OSError, ValueError):
            return  # Diagnostics reports invalid legacy data; migration can be retried.
        state = session.get(SiteConfigState, "default")
        source = session.get(SavedSiteConfigRecord, state.active_saved_config_id) if state and state.active_saved_config_id else None
        metadata = {}
        if source and json.loads(source.site_payload) == bundle.site.model_dump():
            metadata = {"source_preset_id": source.id, "source_revision": source.revision, "source_name": source.name}
        snapshot = make_snapshot(bundle, **metadata)
        stage(snapshot)
        session.add(snapshot)
        session.add(SelectedConfigState(snapshot_id=snapshot.id))
        switch_pointer(snapshot.id)
        try:
            session.commit()
        except Exception:
            session.rollback()
            recover(session)
            raise


def apply_preset(principal, preset_id, payload):
    from app.schemas.config import SiteConfig
    from app.services.config_service import build_runtime_config, get_preset, check_revision
    from app.services.replicated_config import record_replicated_config_change
    principal.require("presets:apply", preset_id=preset_id, target=payload.target)
    if payload.target != "default":
        raise HTTPException(404, "Target not found")
    if (not {"expected_selection_id", "expected_revision", "app_digest", "runtime_digest"} <= payload.model_fields_set
            or payload.expected_revision is None or not payload.app_digest or not payload.runtime_digest):
        raise HTTPException(428, "Review the preset and selected configuration before Apply")
    request_hash = digest({**payload.model_dump(exclude={"request_id"}), "preset_id": preset_id, "actor": principal.user.id})
    with target_lock(), Session(get_engine()) as session:
        principal.require("presets:apply", preset_id=preset_id, target=payload.target)
        previous = recover(session)
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        replay = session.exec(select(ConfigSnapshot).where(ConfigSnapshot.request_id == payload.request_id)).first()
        if replay:
            if replay.request_digest != request_hash:
                raise HTTPException(409, "Apply request identity was already used for another review")
            return bundle_for(replay)
        preset = get_preset(session, preset_id)
        check_revision(preset, payload.expected_revision)
        if (previous.id if previous else None) != payload.expected_selection_id:
            raise HTTPException(409, "Selected configuration changed; review again")
        app = read_app_settings()
        site = SiteConfig.model_validate_json(preset.site_payload)
        try:
            runtime = build_runtime_config(app, site)
        except ValueError:
            raise HTTPException(422, "Preset is incompatible with current sender settings") from None
        if payload.runtime_version != 1 or payload.app_digest != digest(app.model_dump()) or payload.runtime_digest != digest(runtime.model_dump()):
            raise HTTPException(409, "Effective settings changed; open and review the preset again")
        if len(runtime.model_dump_json().encode()) > 65536:
            raise HTTPException(422, "Runtime exceeds the sender manifest limit")
        snapshot = make_snapshot(ConfigBundle(app=app, site=site, runtime=runtime), source_preset_id=preset.id,
                                 source_revision=preset.revision, source_name=preset.name, actor_id=principal.user.id,
                                 request_id=payload.request_id, request_digest=request_hash)
        try:
            stage(snapshot)
            session.add(snapshot)
            state = session.get(SelectedConfigState, "default") or SelectedConfigState(snapshot_id=snapshot.id)
            state.snapshot_id = snapshot.id
            session.add(state)
            record_replicated_config_change(session, app_config=app, site_config=site,
                changed_by_user_id=principal.user.id, change_summary=f"Applied preset {preset.id} revision {preset.revision}", commit=False)
            session.flush()
            switch_pointer(snapshot.id)
            session.commit()
        except Exception:
            session.rollback()
            recover(session)
            raise
        return bundle_for(snapshot)
