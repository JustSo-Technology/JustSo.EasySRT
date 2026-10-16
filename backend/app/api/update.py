from fastapi import APIRouter, Depends, Request

from app.api.deps import require_owner
from app.models.auth import User
from app.schemas.system import UpdateJobStatus, UpdateLaunchResponse, UpdateStatus
from app.services import update_manager
from app.services.update_handoff import create_launch_response

router = APIRouter(prefix="/update", tags=["update"])


@router.get("/status", response_model=UpdateStatus)
def update_status(_: User = Depends(require_owner)):
    return update_manager.get_update_status()


@router.post("/check", response_model=UpdateStatus)
def update_check(_: User = Depends(require_owner)):
    return update_manager.check_for_updates()


@router.post("/launch", response_model=UpdateLaunchResponse)
def update_launch(request: Request, user: User = Depends(require_owner)):
    return create_launch_response(request, user)


@router.post("/install", response_model=UpdateJobStatus)
def update_install(user: User = Depends(require_owner)):
    return update_manager.start_update_job(user)


@router.get("/job", response_model=UpdateJobStatus)
def update_job(_: User = Depends(require_owner)):
    return update_manager.get_update_job()
