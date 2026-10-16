from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.models.auth import User
from app.schemas.system import SystemInfo
from app.services.diagnostics import get_system_info

router = APIRouter(prefix="/system", tags=["system"])


@router.get("", response_model=SystemInfo)
def system_info(_: User = Depends(require_user)):
    return get_system_info()
