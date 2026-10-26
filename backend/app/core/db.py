from pathlib import Path
import shutil
import os
import sqlite3
import tempfile

from sqlmodel import Session, SQLModel, create_engine

from app.core.settings import settings
from app.models.api_token import ApiIdentity, ApiToken, ApiCredential, ApiAudit, ApiCommand
from app.models.auth import SessionRecord, User
from app.models.redundancy import PartnerSyncState, ReplicatedConfigState, ReplicatedConfigVersionRecord
from app.models.site_config import SavedDestinationRecord, SavedInputRecord, SavedSiteConfigRecord, SiteConfigState, ConfigSnapshot, SelectedConfigState


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve()}"


settings.data_dir.mkdir(parents=True, exist_ok=True)


def get_engine():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(_sqlite_url(settings.sqlite_path), connect_args={"check_same_thread": False})


def _publish_backup(temporary: Path, destination: Path):
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    temporary.replace(destination)
    fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # create_all cannot add a column to an existing SQLite table. Back up before
    # the first schema upgrade, and hold SQLite's writer lock through migration.
    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(savedsiteconfigrecord)")}
        if columns and "revision" not in columns:
            backup_path = settings.sqlite_path.with_suffix(".pre-preset-revisions.db")
            if not backup_path.exists():
                with tempfile.NamedTemporaryFile(dir=backup_path.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                try:
                    with sqlite3.connect(settings.sqlite_path) as source, sqlite3.connect(temporary) as backup:
                        source.backup(backup)
                        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise RuntimeError("Database migration backup failed integrity check")
                    _publish_backup(temporary, backup_path)
                finally:
                    temporary.unlink(missing_ok=True)
            for path in (settings.app_config_path, settings.site_config_path, settings.runtime_config_path, settings.sender_env_path):
                if path.exists():
                    destination = path.with_name(path.name + ".pre-preset-revisions")
                    if not destination.exists():
                        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as target:
                            temporary = Path(target.name)
                        try:
                            with path.open("rb") as source, temporary.open("wb") as target:
                                shutil.copyfileobj(source, target)
                            _publish_backup(temporary, destination)
                        finally:
                            temporary.unlink(missing_ok=True)
            connection.execute("ALTER TABLE savedsiteconfigrecord ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migration (version INTEGER PRIMARY KEY)")
        connection.execute("INSERT OR IGNORE INTO schema_migration VALUES (1)")
        connection.commit()
    SQLModel.metadata.create_all(get_engine())
    settings.sqlite_path.chmod(0o600)
    with Session(get_engine()) as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if session.get(ApiIdentity, "local") is None:
            session.add(ApiIdentity())
        session.connection().exec_driver_sql("INSERT OR IGNORE INTO schema_migration VALUES (2)")
        session.commit()


def get_session():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with Session(get_engine()) as session:
        yield session
