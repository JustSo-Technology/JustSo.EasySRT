from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.core.settings import settings
from app.models.auth import User
from app.schemas.system import LogResponse
from app.services.service_control import get_recent_logs

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogResponse)
def logs(user: User = Depends(require_user)):
    return LogResponse(service_name=settings.sender_service_name, lines=get_recent_logs(user))
