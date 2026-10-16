import hashlib
import hmac
import secrets

from itsdangerous import URLSafeTimedSerializer

from app.core.settings import settings


serializer = URLSafeTimedSerializer(settings.secret_key, salt="easysrt-session")
PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PASSWORD_ITERATIONS).hex()
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        parts = password_hash.split("$")
        if len(parts) == 2:
            salt, digest = parts
            iterations = 100_000
        elif len(parts) == 4 and parts[0] == PASSWORD_ALGORITHM:
            _, raw_iterations, salt, digest = parts
            iterations = int(raw_iterations)
        else:
            return False
    except (TypeError, ValueError):
        return False

    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return secrets.compare_digest(check, digest)


def password_needs_rehash(password_hash: str) -> bool:
    return not password_hash.startswith(f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}$")


def issue_session_token(session_id: str) -> str:
    return serializer.dumps({"sid": session_id})


def decode_session_token(token: str, max_age: int) -> str | None:
    try:
        data = serializer.loads(token, max_age=max_age)
        return data.get("sid")
    except Exception:
        return None


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token_for_session(session_id: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"csrf:{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_csrf_token(session_id: str, candidate: str | None) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(csrf_token_for_session(session_id), candidate)
