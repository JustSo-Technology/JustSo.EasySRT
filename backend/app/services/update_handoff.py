from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Request, status

from app.core.settings import settings
from app.models.auth import User, UserRole
from app.schemas.system import UpdateLaunchResponse


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _secret_bytes() -> bytes:
    secret = settings.secret_key.strip()
    if not secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Updater handoff secret is not configured")
    return secret.encode("utf-8")


def _sign(payload_bytes: bytes) -> str:
    digest = hmac.new(_secret_bytes(), payload_bytes, hashlib.sha256).digest()
    return _b64encode(digest)


def _serialize(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _scheme_for_request(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip()
    return request.url.scheme or "http"


def _host_for_request(request: Request) -> str:
    forwarded_host = request.headers.get("x-forwarded-host")
    host_header = forwarded_host.split(",")[0].strip() if forwarded_host else request.headers.get("host", "")
    try:
        return urlsplit(f"//{host_header}").hostname or "localhost"
    except ValueError:
        return "localhost"


def _format_host_for_url(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _return_url(request: Request) -> str:
    origin = urlsplit(settings.frontend_origin)
    # A configured public origin is authoritative, including its scheme and port.
    if origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return settings.frontend_origin.rstrip("/") + "/"
    # Local/default installs can be reached by LAN address instead of localhost.
    scheme = _scheme_for_request(request)
    host = _format_host_for_url(_host_for_request(request))
    port = origin.port
    suffix = f":{port}" if port else ""
    return f"{scheme}://{host}{suffix}/"


def _updater_origin(request: Request) -> str:
    if settings.updater_public_origin:
        return settings.updater_public_origin.rstrip("/")
    scheme = _scheme_for_request(request)
    host = _format_host_for_url(_host_for_request(request))
    return f"{scheme}://{host}:{settings.updater_port}"


def create_launch_response(request: Request, user: User) -> UpdateLaunchResponse:
    expires_at = _now() + timedelta(seconds=settings.updater_token_ttl_seconds)
    payload = {
        "purpose": "updater-handoff",
        "sub": user.id,
        "username": user.username,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
        "exp": int(expires_at.timestamp()),
        "return_url": _return_url(request),
    }
    payload_bytes = _serialize(payload)
    token = f"{_b64encode(payload_bytes)}.{_sign(payload_bytes)}"
    updater_url = f"{_updater_origin(request)}/?token={quote(token)}"
    return UpdateLaunchResponse(updater_url=updater_url, expires_at=expires_at.isoformat())


def _decode_token(token: str, purpose: str) -> dict[str, Any]:
    try:
        encoded_payload, encoded_sig = token.split(".", 1)
        payload_bytes = _b64decode(encoded_payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid updater handoff token") from exc

    expected_sig = _sign(payload_bytes)
    if not hmac.compare_digest(encoded_sig, expected_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid updater handoff token")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid updater handoff token") from exc

    if not isinstance(payload, dict) or payload.get("purpose") != purpose:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid updater token scope")

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= int(_now().timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Updater handoff token expired")

    if payload.get("role") != UserRole.OWNER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")

    return payload


def decode_handoff_token(token: str) -> dict[str, Any]:
    return _decode_token(token, "updater-handoff")


def exchange_handoff_token(token: str) -> dict[str, str]:
    payload = decode_handoff_token(token)
    payload["purpose"] = "updater-session"
    expires_at = _now() + timedelta(seconds=settings.updater_session_ttl_seconds)
    payload["exp"] = int(expires_at.timestamp())
    payload_bytes = _serialize(payload)
    return {
        "token": f"{_b64encode(payload_bytes)}.{_sign(payload_bytes)}",
        "expires_at": expires_at.isoformat(),
        "return_url": payload["return_url"],
    }


def decode_updater_session(token: str) -> dict[str, Any]:
    return _decode_token(token, "updater-session")


def user_from_handoff(payload: dict[str, Any]) -> User:
    return User(
        id=str(payload.get("sub") or "updater-owner"),
        username=str(payload.get("username") or "owner"),
        password_hash="updater-handoff",
        role=UserRole(str(payload.get("role") or UserRole.OWNER.value)),
        disabled=False,
    )
