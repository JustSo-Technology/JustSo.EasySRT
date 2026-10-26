from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from pydantic import ValidationError
from app.services.api_boundary import boundary, api_error, install_access_log_filter
from app.api.v1 import tokens, integration
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, config, config_transfer, diagnostics, logs, redundancy, service, system, update
from app.core.db import init_db
from app.core.settings import settings
from app.services.security import decode_session_token, verify_csrf_token
from app.services.config_snapshots import migrate_selection


@asynccontextmanager
async def lifespan(_: FastAPI):
    install_access_log_filter()
    init_db()
    migrate_selection()
    from app.services.api_tokens import maintain_history
    maintain_history()
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
    if request.url.path.startswith(("/api/config", "/api/service")):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if settings.frontend_origin.lower().startswith("https://"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.middleware("http")(boundary)


@app.exception_handler(HTTPException)
async def api_http_error(request, exc):
    if request.url.path.startswith("/api/v1"):
        from app.services.api_redaction import redact
        return api_error(exc.status_code, redact(str(exc.detail)), request.state.api_request_id, exc.headers)
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def api_validation_error(request, exc):
    if request.url.path.startswith("/api/v1"):
        return api_error(422, "Invalid payload; check the documented field types and constraints", request.state.api_request_id)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(ValidationError)
async def api_model_error(request, exc):
    if request.url.path.startswith("/api/v1"):
        return api_error(422, "Invalid payload; check the documented field types and constraints", request.state.api_request_id)
    raise exc


app.include_router(tokens.router)
app.include_router(integration.router)

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
