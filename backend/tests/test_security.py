from __future__ import annotations

import hashlib

from app.services.security import hash_password, password_needs_rehash, verify_password


def test_password_hash_uses_current_work_factor():
    password_hash = hash_password("supersecurepass")

    assert password_hash.startswith("pbkdf2_sha256$600000$")
    assert verify_password("supersecurepass", password_hash)
    assert not verify_password("incorrect-password", password_hash)
    assert not password_needs_rehash(password_hash)


def test_legacy_password_hash_remains_compatible():
    password = "supersecurepass"
    salt = "legacy-salt"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    password_hash = f"{salt}${digest}"

    assert verify_password(password, password_hash)
    assert password_needs_rehash(password_hash)
