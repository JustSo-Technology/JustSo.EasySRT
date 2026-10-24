from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, config, config_transfer, diagnostics, logs, redundancy, service, system, update
from app.core.db import init_db
from app.core.settings import settings
from app.services.security import decode_session_token, verify_csrf_token
from app.services.config_service import migrate_legacy_runtime


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    migrate_legacy_runtime()
    yield


production = settings.environment.lower() == "production"
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url=None if production else "/docs",
    redoc_url=None if production else "/redoc",
    openapi_url=None if production else "/openapi.json",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/bootstrap-owner"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method in UNSAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
        session_token = request.cookies.get(settings.session_cookie_name)
        if session_token:
            session_id = decode_session_token(session_token, settings.session_max_age_seconds)
            candidate = request.headers.get("X-CSRF-Token")
            if not session_id or not verify_csrf_token(session_id, candidate):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Missing or invalid CSRF token"},
                )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if settings.frontend_origin.lower().startswith("https://"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(config.router, prefix=settings.api_prefix)
app.include_router(config_transfer.router, prefix=settings.api_prefix)
app.include_router(service.router, prefix=settings.api_prefix)
app.include_router(logs.router, prefix=settings.api_prefix)
app.include_router(diagnostics.router, prefix=settings.api_prefix)
app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(redundancy.router, prefix=settings.api_prefix)
app.include_router(update.router, prefix=settings.api_prefix)


@app.get("/health")
def health():
    return {"ok": True}
