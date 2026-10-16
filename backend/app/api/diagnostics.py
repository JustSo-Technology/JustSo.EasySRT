from fastapi import APIRouter, Depends

from app.api.deps import require_user
from app.models.auth import User
from app.schemas.system import DiagnosticsResponse
from app.services.diagnostics import get_diagnostics

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("", response_model=DiagnosticsResponse)
def diagnostics(_: User = Depends(require_user)):
    return get_diagnostics()
