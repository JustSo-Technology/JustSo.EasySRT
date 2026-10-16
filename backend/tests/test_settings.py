from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "secret_key": "a" * 64,
        "frontend_origin": "https://easysrt.example.com",
        "session_cookie_secure": True,
        "trusted_hosts": "easysrt.example.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError, match="EASYSRT_SECRET_KEY"):
        production_settings(secret_key="dev-change-me")


def test_production_requires_explicit_insecure_http_opt_in():
    with pytest.raises(ValidationError, match="EASYSRT_ALLOW_INSECURE_HTTP"):
        production_settings(
            frontend_origin="http://192.0.2.10:5173",
            session_cookie_secure=False,
        )


def test_production_allows_explicit_lan_http_mode():
    configured = production_settings(
        frontend_origin="http://192.0.2.10:5173",
        session_cookie_secure=False,
        allow_insecure_http=True,
        trusted_hosts="192.0.2.10,localhost",
    )

    assert configured.allowed_hosts == ["192.0.2.10", "localhost"]


def test_https_requires_secure_session_cookie():
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        production_settings(session_cookie_secure=False)
