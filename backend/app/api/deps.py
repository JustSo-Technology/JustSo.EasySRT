from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.settings import settings
from app.models.auth import SessionRecord, User, UserRole
from app.services.security import decode_session_token, hash_session_token


def require_user(
    session: Session = Depends(get_session),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> User:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    session_id = decode_session_token(session_token, settings.session_max_age_seconds)
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

    record = session.exec(select(SessionRecord).where(SessionRecord.id == session_id)).first()
    if not record or record.revoked_at is not None or record.token_hash != hash_session_token(session_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = session.get(User, record.user_id)
    if not user or user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    return user


def require_owner(user: User = Depends(require_user)) -> User:
    if user.role != UserRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return user


def config_write_session(_: User = Depends(require_user), session: Session = Depends(get_session)) -> Session:
    # Authenticate before locking, and acquire the writer lock before runtime
    # file writes so an import cannot race with local preset activation.
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    return session
