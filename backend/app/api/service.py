from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.api.deps import require_user
from app.models.auth import User
from app.schemas.system import ServiceStatus
from app.services.service_control import ServiceCommandFailure, get_service_status, perform_service_action

router = APIRouter(prefix="/service", tags=["service"])


@router.get("/status", response_model=ServiceStatus)
def service_status(user: User = Depends(require_user)):
    return get_service_status(user)


@router.post("/{action}", response_model=ServiceStatus)
def service_action(action: str, user: User = Depends(require_user)):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=400, detail="Unsupported action")
    try:
        return perform_service_action(action, user)
    except ServiceCommandFailure as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.payload.model_dump())
