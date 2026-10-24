from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.schemas.system import ServiceStatus
from app.services.service_control import ServiceCommandFailure, get_service_status, perform_service_action
from app.services.authorization import Principal, require_principal

router = APIRouter(prefix="/service", tags=["service"])


class ServiceActionRequest(BaseModel):
    expected_selection_id: str | None = None


def filter_actions(snapshot: ServiceStatus, principal: Principal):
    snapshot.allowed_actions = [action for action in snapshot.allowed_actions
                               if principal.allows(f"service:{action}", target="default")]
    return snapshot


@router.get("/status", response_model=ServiceStatus)
def service_status(principal: Principal = Depends(require_principal)):
    principal.require("service:read", target="default")
    return filter_actions(get_service_status(principal.user), principal)


@router.post("/{action}", response_model=ServiceStatus)
def service_action(action: str, payload: ServiceActionRequest | None = None, principal: Principal = Depends(require_principal)):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(400, "Unsupported action")
    principal.require(f"service:{action}", target="default")
    try:
        return filter_actions(perform_service_action(action, principal.user,
            expected_selection_id=payload.expected_selection_id if payload else None), principal)
    except ServiceCommandFailure as exc:
        return JSONResponse(status_code=exc.status_code, content=filter_actions(exc.payload, principal).model_dump(mode="json"))
