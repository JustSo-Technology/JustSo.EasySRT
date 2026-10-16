from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import config_write_session, require_user
from app.core.db import get_session
from app.models.auth import User
from app.schemas.config import (
    AppConfig,
    ConfigBundle,
    SavedDestinationCreateRequest,
    SavedDestinationEntry,
    SavedInputCreateRequest,
    SavedInputEntry,
    SavedSiteConfigCreateRequest,
    SavedSiteConfigRenameRequest,
    SavedSiteConfigResponse,
    SavedSiteConfigSummary,
    SiteConfig,
)
from app.services.config_service import (
    clear_active_saved_site_config,
    delete_saved_site_config,
    list_saved_destinations,
    list_saved_inputs,
    list_saved_site_configs,
    load_bundle,
    load_saved_site_config,
    rename_saved_site_config,
    save_bundle,
    save_destination,
    save_input,
    save_named_site_config,
)
from app.services.replicated_config import record_replicated_config_change

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigBundle)
def get_config(_: User = Depends(require_user)):
    return load_bundle()


@router.put("/app", response_model=ConfigBundle)
def update_app_config(payload: AppConfig, session: Session = Depends(config_write_session), user: User = Depends(require_user)):
    bundle = load_bundle()
    saved_bundle = save_bundle(payload, bundle.site)
    record_replicated_config_change(
        session,
        app_config=saved_bundle.app,
        site_config=saved_bundle.site,
        changed_by_user_id=user.id,
        change_summary="Updated app settings",
    )
    return saved_bundle


@router.put("/site", response_model=ConfigBundle)
def update_site_config(payload: SiteConfig, session: Session = Depends(config_write_session), user: User = Depends(require_user)):
    bundle = load_bundle()
    saved_bundle = save_bundle(bundle.app, payload)
    clear_active_saved_site_config(session)
    record_replicated_config_change(
        session,
        app_config=saved_bundle.app,
        site_config=saved_bundle.site,
        changed_by_user_id=user.id,
        change_summary="Updated live site configuration",
    )
    return saved_bundle


@router.get("/saved", response_model=list[SavedSiteConfigSummary])
def get_saved_site_configs(session: Session = Depends(get_session), _: User = Depends(require_user)):
    return list_saved_site_configs(session)


@router.post("/saved", response_model=SavedSiteConfigResponse)
def create_or_update_saved_site_config(
    payload: SavedSiteConfigCreateRequest,
    session: Session = Depends(config_write_session),
    user: User = Depends(require_user),
):
    bundle = load_bundle()
    saved_config, saved_bundle = save_named_site_config(
        session,
        payload.name,
        payload.site,
        bundle.app,
        created_by_user_id=user.id,
        overwrite=payload.overwrite,
    )
    record_replicated_config_change(
        session,
        app_config=saved_bundle.app,
        site_config=saved_bundle.site,
        changed_by_user_id=user.id,
        change_summary=f'Activated saved site config "{payload.name}"',
    )
    return SavedSiteConfigResponse(saved_config=saved_config, bundle=saved_bundle)


@router.post("/saved/{saved_config_id}/load", response_model=ConfigBundle)
def apply_saved_site_config(saved_config_id: str, session: Session = Depends(config_write_session), _: User = Depends(require_user)):
    bundle = load_bundle()
    saved_bundle = load_saved_site_config(session, saved_config_id, bundle.app)
    record_replicated_config_change(
        session,
        app_config=saved_bundle.app,
        site_config=saved_bundle.site,
        changed_by_user_id=None,
        change_summary="Loaded saved site configuration",
    )
    return saved_bundle


@router.patch("/saved/{saved_config_id}", response_model=SavedSiteConfigSummary)
def update_saved_site_config_name(
    saved_config_id: str,
    payload: SavedSiteConfigRenameRequest,
    session: Session = Depends(config_write_session),
    _: User = Depends(require_user),
):
    return rename_saved_site_config(session, saved_config_id, payload.name)


@router.delete("/saved/{saved_config_id}")
def remove_saved_site_config(saved_config_id: str, session: Session = Depends(config_write_session), _: User = Depends(require_user)):
    delete_saved_site_config(session, saved_config_id)
    return {"ok": True}


@router.get("/saved-inputs", response_model=list[SavedInputEntry])
def get_saved_inputs(session: Session = Depends(get_session), _: User = Depends(require_user)):
    return list_saved_inputs(session)


@router.post("/saved-inputs", response_model=SavedInputEntry)
def create_saved_input(payload: SavedInputCreateRequest, session: Session = Depends(config_write_session), _: User = Depends(require_user)):
    return save_input(session, payload.input)


@router.get("/saved-destinations", response_model=list[SavedDestinationEntry])
def get_saved_destinations(session: Session = Depends(get_session), _: User = Depends(require_user)):
    return list_saved_destinations(session)


@router.post("/saved-destinations", response_model=SavedDestinationEntry)
def create_saved_destination(
    payload: SavedDestinationCreateRequest,
    session: Session = Depends(config_write_session),
    _: User = Depends(require_user),
):
    return save_destination(session, payload.destination)
