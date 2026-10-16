from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import require_user
from app.core.db import get_session
from app.models.auth import User
from app.schemas.redundancy import RedundancyStatus
from app.schemas.replicated_config import PartnerAckRequest, ReplicatedConfigStatus
from app.services.redundancy import get_redundancy_status
from app.services.replicated_config import acknowledge_partner_version, get_replicated_config_status

router = APIRouter(prefix="/redundancy", tags=["redundancy"])


@router.get("/status", response_model=RedundancyStatus)
def redundancy_status(_: User = Depends(require_user)):
    return get_redundancy_status()


@router.get("/config-sync", response_model=ReplicatedConfigStatus)
def replicated_config_status(session: Session = Depends(get_session), _: User = Depends(require_user)):
    return get_replicated_config_status(session)


@router.post("/partner-ack", response_model=ReplicatedConfigStatus)
def partner_acknowledgment(
    payload: PartnerAckRequest,
    session: Session = Depends(get_session),
    _: User = Depends(require_user),
):
    return acknowledge_partner_version(session, payload)
