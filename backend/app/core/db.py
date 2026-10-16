from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.core.settings import settings
from app.models.auth import SessionRecord, User
from app.models.redundancy import PartnerSyncState, ReplicatedConfigState, ReplicatedConfigVersionRecord
from app.models.site_config import SavedDestinationRecord, SavedInputRecord, SavedSiteConfigRecord, SiteConfigState


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve()}"


settings.data_dir.mkdir(parents=True, exist_ok=True)


def get_engine():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(_sqlite_url(settings.sqlite_path), connect_args={"check_same_thread": False})


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(get_engine())


def get_session():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with Session(get_engine()) as session:
        yield session
