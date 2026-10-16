from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from app.api.deps import require_owner, require_user
from app.core.db import get_session
from app.core.settings import settings
from app.models.auth import SessionRecord, User, UserRole
from app.schemas.auth import (
    AuthStatus,
    BootstrapStatus,
    ChangePasswordRequest,
    LoginRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.security import (
    csrf_token_for_session,
    decode_session_token,
    hash_password,
    hash_session_token,
    issue_session_token,
    password_needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, role=user.role, disabled=user.disabled)


@router.get("/bootstrap-status", response_model=BootstrapStatus)
def bootstrap_status(session: Session = Depends(get_session)):
    return BootstrapStatus(requires_bootstrap=session.exec(select(User)).first() is None)


@router.post("/login", response_model=AuthStatus)
def login(payload: LoginRequest, response: Response, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == payload.username)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User disabled")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.session_max_age_seconds)
    record = SessionRecord(user_id=user.id, expires_at=expires_at, token_hash="")
    session.add(record)
    session.commit()
    session.refresh(record)

    token = issue_session_token(record.id)
    record.token_hash = hash_session_token(token)
    user.last_login_at = datetime.now(timezone.utc)
    session.add(record)
    session.add(user)
    session.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        max_age=settings.session_max_age_seconds,
    )
    return AuthStatus(
        authenticated=True,
        user=_user_response(user),
        csrf_token=csrf_token_for_session(record.id),
    )


@router.post("/logout", response_model=AuthStatus)
def logout(
    response: Response,
    session: Session = Depends(get_session),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
):
    session_id = decode_session_token(session_token or "", settings.session_max_age_seconds)
    if session_id:
        record = session.get(SessionRecord, session_id)
        if record and record.revoked_at is None:
            record.revoked_at = datetime.now(timezone.utc)
            session.add(record)
            session.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )
    return AuthStatus(authenticated=False, user=None)


@router.get("/me", response_model=AuthStatus)
def me(
    user: User = Depends(require_user),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
):
    session_id = decode_session_token(session_token or "", settings.session_max_age_seconds)
    return AuthStatus(
        authenticated=True,
        user=_user_response(user),
        csrf_token=csrf_token_for_session(session_id) if session_id else None,
    )


@router.post("/change-password", response_model=AuthStatus)
def change_password(
    payload: ChangePasswordRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_user),
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password incorrect")
    user.password_hash = hash_password(payload.new_password)
    session.add(user)
    session.commit()
    session_id = decode_session_token(session_token or "", settings.session_max_age_seconds)
    return AuthStatus(
        authenticated=True,
        user=_user_response(user),
        csrf_token=csrf_token_for_session(session_id) if session_id else None,
    )


@router.post("/bootstrap-owner", response_model=AuthStatus)
def bootstrap_owner(payload: UserCreateRequest, response: Response, session: Session = Depends(get_session)):
    # Serialize the first-user check and insert across SQLite connections/workers.
    password_hash = hash_password(payload.password)
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    existing = session.exec(select(User)).first()
    if existing:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Owner already exists")
    user = User(username=payload.username, password_hash=password_hash, role=UserRole.OWNER)
    session.add(user)
    session.commit()
    session.refresh(user)
    return login(LoginRequest(username=payload.username, password=payload.password), response, session)


@router.get("/users", response_model=list[UserResponse])
def list_users(session: Session = Depends(get_session), _: User = Depends(require_owner)):
    users = session.exec(select(User)).all()
    return [_user_response(user) for user in users]


@router.post("/users", response_model=UserResponse)
def create_user(payload: UserCreateRequest, session: Session = Depends(get_session), _: User = Depends(require_owner)):
    if session.exec(select(User).where(User.username == payload.username)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    user = User(username=payload.username, password_hash=hash_password(payload.password), role=payload.role)
    session.add(user)
    session.commit()
    session.refresh(user)
    return _user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_owner),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target_role = payload.role if payload.role is not None else user.role
    target_disabled = payload.disabled if payload.disabled is not None else user.disabled
    is_owner_access_being_removed = user.role == UserRole.OWNER and (target_role != UserRole.OWNER or target_disabled)
    if is_owner_access_being_removed:
        if user.id == current_user.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own owner access")
        remaining_owner = session.exec(
            select(User).where(User.role == UserRole.OWNER, User.disabled == False, User.id != user.id)  # noqa: E712
        ).first()
        if remaining_owner is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one enabled owner must remain")
    if payload.role is not None:
        user.role = payload.role
    if payload.disabled is not None:
        user.disabled = payload.disabled
    session.add(user)
    session.commit()
    session.refresh(user)
    return _user_response(user)
