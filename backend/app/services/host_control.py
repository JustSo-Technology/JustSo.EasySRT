from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any

from app.core.settings import settings
from app.models.auth import User


@dataclass
class HostControlError(Exception):
    message: str
    code: str = "helper_error"
    details: dict[str, Any] | None = None


def _actor_payload(user: User | None) -> dict[str, str | None]:
    if user is None:
        return {"id": None, "username": None, "role": None}
    return {"id": user.id, "username": user.username, "role": str(user.role)}


def request_helper(action: str, *, actor: User | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    message = {
        "action": action,
        "actor": _actor_payload(actor),
        "payload": payload or {},
    }
    encoded = (json.dumps(message) + "\n").encode("utf-8")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(settings.helper_request_timeout_seconds)
    try:
        sock.connect(str(settings.helper_socket_path))
        sock.sendall(encoded)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    except FileNotFoundError as exc:
        raise HostControlError("Local control helper socket is not available", code="helper_unavailable") from exc
    except ConnectionRefusedError as exc:
        raise HostControlError("Local control helper is not accepting connections", code="helper_unavailable") from exc
    except TimeoutError as exc:
        raise HostControlError("Timed out waiting for the local control helper", code="helper_timeout") from exc
    except OSError as exc:
        raise HostControlError(f"Local control helper error: {exc}", code="helper_unavailable") from exc
    finally:
        sock.close()

    raw = b"".join(chunks).decode("utf-8").strip()
    if not raw:
        raise HostControlError("Local control helper returned an empty response", code="helper_protocol_error")

    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HostControlError("Local control helper returned invalid JSON", code="helper_protocol_error") from exc

    if not response.get("ok", False):
        raise HostControlError(
            response.get("error", "Local control helper request failed"),
            code=response.get("error_code", "helper_error"),
            details=response.get("details"),
        )

    data = response.get("data")
    if not isinstance(data, dict):
        raise HostControlError("Local control helper returned an invalid payload", code="helper_protocol_error")
    return data

