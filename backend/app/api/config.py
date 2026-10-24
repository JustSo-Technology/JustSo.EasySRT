from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

from app.api.deps import config_write_session
from app.core.db import get_session
from app.schemas.config import (
    AppConfig, ConfigBundle, SavedDestinationCreateRequest, SavedDestinationEntry,
    SavedInputCreateRequest, SavedInputEntry, SavedSiteConfigCreateRequest,
    SavedSiteConfigRenameRequest, SavedSiteConfigResponse, SavedSiteConfigSummary,
    SavedSiteConfigDetail, SavedSiteConfigUpdateRequest, ApplyPresetRequest,
)
from app.services.authorization import Principal, require_principal
from app.services import config_service as config
from app.services.config_snapshots import apply_preset, durable_write, target_lock
from app.core.settings import settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigBundle)
def get_config(response: Response, principal: Principal = Depends(require_principal)):
    principal.require("presets:read", target="default")
    response.headers["Cache-Control"] = "no-store"
    bundle = config.load_bundle()
    bundle.capabilities = principal.capabilities
    return bundle


@router.put("/app", response_model=ConfigBundle)
def update_app_config(payload: AppConfig, principal: Principal = Depends(require_principal)):
    principal.require("config-app:update", target="default")
    with target_lock():
        durable_write(settings.app_config_path, payload.model_dump_json())
        return config.load_bundle()


@router.put("/site")
def retired_site_update(principal: Principal = Depends(require_principal)):
    raise HTTPException(410, "Reload the application. Save a preset, review it and explicitly Apply it instead")


@router.get("/saved", response_model=list[SavedSiteConfigSummary])
def get_saved_site_configs(session: Session = Depends(get_session), principal: Principal = Depends(require_principal)):
    return [record for record in config.list_saved_site_configs(session)
            if principal.allows("presets:read", preset_id=record.id)]


@router.get("/saved/{preset_id}", response_model=SavedSiteConfigDetail)
def open_preset(preset_id: str, response: Response, expected_revision: int | None = None, session: Session = Depends(get_session), principal: Principal = Depends(require_principal)):
    principal.require("presets:read", preset_id=preset_id)
    response.headers["Cache-Control"] = "no-store"
    return config.preview_preset(session, preset_id, expected_revision)


@router.post("/saved", response_model=SavedSiteConfigResponse)
def create_preset(payload: SavedSiteConfigCreateRequest, session: Session = Depends(config_write_session), principal: Principal = Depends(require_principal)):
    if payload.overwrite:
        if not payload.target_id or payload.expected_revision is None:
            raise HTTPException(428, "Overwrite requires a target preset ID and expected revision; open the preset first")
        principal.require("presets:update", preset_id=payload.target_id)
        record = config.get_preset(session, payload.target_id)
        if record.name != payload.name:
            raise HTTPException(409, "Preset name changed; open it again")
        saved = config.update_saved_site_config(session, record.id, payload.site, payload.expected_revision)
    else:
        principal.require("presets:create")
        saved = config.save_named_site_config(session, payload.name, payload.site, principal.user.id)
    session.commit()
    return SavedSiteConfigResponse(saved_config=saved)


@router.put("/saved/{preset_id}", response_model=SavedSiteConfigResponse)
def update_preset(preset_id: str, payload: SavedSiteConfigUpdateRequest, session: Session = Depends(config_write_session), principal: Principal = Depends(require_principal)):
    principal.require("presets:update", preset_id=preset_id)
    saved = config.update_saved_site_config(session, preset_id, payload.site, payload.expected_revision)
    session.commit()
    return SavedSiteConfigResponse(saved_config=saved)


@router.post("/saved/{preset_id}/load")
def retired_load(preset_id: str, principal: Principal = Depends(require_principal)):
    raise HTTPException(410, "Reload the application. GET the preset to open it, or use explicit Apply with review preconditions")


@router.post("/saved/{preset_id}/apply", response_model=ConfigBundle)
def apply(preset_id: str, payload: ApplyPresetRequest, principal: Principal = Depends(require_principal)):
    return apply_preset(principal, preset_id, payload)


@router.patch("/saved/{preset_id}", response_model=SavedSiteConfigSummary)
def rename(preset_id: str, payload: SavedSiteConfigRenameRequest, session: Session = Depends(config_write_session), principal: Principal = Depends(require_principal)):
    principal.require("presets:update", preset_id=preset_id)
    saved = config.rename_saved_site_config(session, preset_id, payload.name, payload.expected_revision)
    session.commit()
    return saved


@router.delete("/saved/{preset_id}")
def delete(preset_id: str, expected_revision: int | None = None, session: Session = Depends(config_write_session), principal: Principal = Depends(require_principal)):
    principal.require("presets:delete", preset_id=preset_id)
    config.delete_saved_site_config(session, preset_id, expected_revision)
    session.commit()
    return {"ok": True}


@router.get("/saved-inputs", response_model=list[SavedInputEntry])
def get_saved_inputs(session: Session = Depends(get_session), principal: Principal = Depends(require_principal)):
    principal.require("presets:read")
    return config.list_saved_inputs(session)


@router.post("/saved-inputs", response_model=SavedInputEntry)
def create_saved_input(payload: SavedInputCreateRequest, session: Session = Depends(config_write_session), principal: Principal = Depends(require_principal)):
    principal.require("inputs:create")
    return config.save_input(session, payload.input)


@router.get("/saved-destinations", response_model=list[SavedDestinationEntry])
def get_saved_destinations(session: Session = Depends(get_session), principal: Principal = Depends(require_principal)):
    principal.require("presets:read")
    return config.list_saved_destinations(session)


@router.post("/saved-destinations", response_model=SavedDestinationEntry)
def create_saved_destination(payload: SavedDestinationCreateRequest, session: Session = Depends(config_write_session), principal: Principal = Depends(require_principal)):
    principal.require("destinations:create")
    return config.save_destination(session, payload.destination)
