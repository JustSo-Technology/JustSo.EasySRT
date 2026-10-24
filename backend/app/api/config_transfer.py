from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.core.db import get_session
from app.services.authorization import Principal, require_principal
from app.services import config_transfer as transfer

router = APIRouter(prefix="/config/transfer", tags=["configuration transfer"])


def editor(principal: Principal = Depends(require_principal)):
    # Transfer exposes collection-wide conflict metadata; require collection read.
    principal.require("presets:read")
    if not (principal.allows("presets:create") or principal.allows("presets:update")):
        raise HTTPException(403, "Preset library editing permission required")
    return principal

async def import_request(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > transfer.MAX_BYTES:
            raise HTTPException(413, "Configuration request exceeds 1 MiB")
    return transfer.parse_request(bytes(raw))


@router.get("/export")
def export(session: Session = Depends(get_session), _: Principal = Depends(editor)):
    return JSONResponse(transfer.export_document(session), headers={
        "Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="easysrt-configurations.json"'})


@router.post("/preview")
async def preview(request: Request, session: Session = Depends(get_session), principal: Principal = Depends(editor)):
    result = await run_in_threadpool(transfer.preview, session, await import_request(request), principal.user, principal)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/import")
async def import_config(request: Request, session: Session = Depends(get_session), principal: Principal = Depends(editor)):
    result = await run_in_threadpool(transfer.commit_import, session, await import_request(request), principal.user, principal)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
