"""Database-backed opaque credentials, role ceilings, quotas and audit records."""
from collections import OrderedDict
from threading import Lock
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
import time
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPBearer
from sqlmodel import Session, select, delete
from sqlalchemy import func

from app.core.db import get_engine
from app.core.settings import settings
from app.models.api_token import ApiAudit, ApiCommand, ApiCredential, ApiIdentity, ApiToken
from app.models.auth import User
from app.services.api_scopes import PRESETS, ScopeGrant, role_allows
from app.services.security import verify_password


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def instance_id(session):
    identity = session.get(ApiIdentity, 'local')
    if not identity:
        raise HTTPException(503, 'API identity is unavailable')
    return identity.instance_id


def audit(session, actor_id, action, *, token_id=None, resource_id='', outcome='success', request_id='', detail=None):
    session.add(ApiAudit(actor_id=actor_id, token_id=token_id, action=action, resource_id=resource_id,
                         outcome=outcome, request_id=request_id, detail_json=json.dumps(detail or {})))


def reauthenticate(user, password):
    if not password or not verify_password(password, user.password_hash):
        raise HTTPException(403, 'Current owner password is required')


def validate_expiry(value):
    if value.tzinfo is None:
        raise HTTPException(422, 'Expiry must include a timezone')
    if not utcnow() < value <= utcnow() + timedelta(days=365):
        raise HTTPException(422, 'Expiry must be in the future and within 365 days')
    return aware(value)


def validate_grants(session, owner, grants):
    from app.models.site_config import SavedDestinationRecord, SavedInputRecord, SavedSiteConfigRecord
    result = []
    identity = instance_id(session)
    models = {'preset': SavedSiteConfigRecord, 'input': SavedInputRecord, 'destination': SavedDestinationRecord}
    for value in grants:
        grant = value if isinstance(value, ScopeGrant) else ScopeGrant.model_validate(value)
        if not role_allows(owner.role, grant.scope):
            raise HTTPException(403, 'A grant exceeds the owning account role')
        if grant.kind == 'instance' and grant.resource_id != identity:
            raise HTTPException(422, 'Instance grants must name this instance')
        if grant.kind in models and grant.resource_id != '*' and session.get(models[grant.kind], grant.resource_id) is None:
            raise HTTPException(422, 'Unknown grant resource')
        if grant not in result:
            result.append(grant)
    return [g.model_dump() for g in result]


def issue_credential(session, token):
    secret = secrets.token_urlsafe(32)
    credential = ApiCredential(token_id=token.id, secret_hash=hashlib.sha256(secret.encode()).hexdigest())
    session.add(credential)
    return f'esrt_{credential.id}_{secret}'


def token_status(token):
    return 'revoked' if token.revoked_at else 'expired' if aware(token.expires_at) <= utcnow() else 'active'


def metadata(session, token):
    owner = session.get(User, token.owner_id)
    credentials = session.exec(select(ApiCredential).where(ApiCredential.token_id == token.id).order_by(ApiCredential.created_at.desc()).limit(20)).all()
    status = token_status(token)
    if status == 'active' and (not owner or owner.disabled):
        status = 'owner-disabled'
    grants = json.loads(token.grants_json)
    last_used = session.exec(select(func.max(ApiCredential.last_used_at)).where(ApiCredential.token_id == token.id)).one()
    return {'id': token.id, 'instance_id': token.instance_id, 'name': token.name, 'integration': token.integration,
            'owner_id': token.owner_id, 'creator_id': token.creator_id, 'preset': token.preset,
            'preset_version': token.preset_version, 'preset_customized': token.preset_customized, 'revision': token.revision, 'grants': grants,
            'effective_grants': [g for g in grants if owner and not owner.disabled and status == 'active' and role_allows(owner.role, g['scope'])],
            'status': status, 'created_at': aware(token.created_at), 'expires_at': aware(token.expires_at),
            'revoked_at': aware(token.revoked_at) if token.revoked_at else None,
            'last_used_at': aware(last_used) if last_used else None,
            'credentials': [{'id': c.id, 'prefix': f'esrt_{c.id[:8]}…', 'created_at': aware(c.created_at),
                             'last_used_at': aware(c.last_used_at) if c.last_used_at else None, 'retire_at': aware(c.retire_at) if c.retire_at else None, 'revoked_at': aware(c.revoked_at) if c.revoked_at else None}
                            for c in credentials]}


def quota(key, limit, seconds=60):
    # One durable bounded row per quota key. Shared by local API workers.
    identity = 'quota:' + hashlib.sha256(key.encode()).hexdigest()
    window = int(time.time()) // seconds
    with Session(get_engine()) as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        row = session.get(ApiCommand, identity)
        count = int(row.result_json or '0') if row and row.request_hash == str(window) else 0
        if count >= limit:
            raise HTTPException(429, 'Rate limit exceeded', headers={'Retry-After': str(seconds - int(time.time()) % seconds)})
        if row is None:
            row = ApiCommand(id=identity, token_id='quota', request_hash=str(window))
        row.request_hash, row.result_json = str(window), str(count + 1)
        session.add(row)
        session.commit()


_attempts = OrderedDict()
_attempt_lock = Lock()


def authentication_attempt(peer):
    # Pre-auth memory is capped; spoofed identities cannot create database rows.
    window = int(time.monotonic()) // 60
    with _attempt_lock:
        old_window, count = _attempts.pop(peer, (window, 0))
        count = count + 1 if old_window == window else 1
        _attempts[peer] = (window, count)
        while len(_attempts) > 4096:
            _attempts.popitem(last=False)
        if count > 300:
            raise HTTPException(429, 'Authentication attempt limit exceeded', headers={'Retry-After': '60'})


def maintain_history():
    with Session(get_engine()) as session:
        marker = session.get(ApiCommand, 'maintenance')
        if marker and (utcnow() - aware(marker.created_at)).total_seconds() < 86400:
            return
        session.rollback()
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        marker = session.get(ApiCommand, 'maintenance')
        if marker and (utcnow() - aware(marker.created_at)).total_seconds() < 86400:
            return
        session.exec(delete(ApiAudit).where(ApiAudit.created_at < utcnow() - timedelta(days=max(1, settings.api_audit_retention_days))))
        session.exec(delete(ApiCommand).where(ApiCommand.token_id != 'quota', ApiCommand.id != 'maintenance', ApiCommand.created_at < utcnow() - timedelta(hours=max(1, settings.api_command_retention_hours))))
        marker = marker or ApiCommand(id='maintenance', token_id='maintenance', request_hash='')
        marker.created_at = utcnow()
        session.add(marker)
        session.commit()


def unauthorized():
    return HTTPException(401, 'Invalid, expired or revoked API token', headers={'WWW-Authenticate': 'Bearer'})


def load_valid(session, credential_id):
    credential = session.get(ApiCredential, credential_id)
    token = session.get(ApiToken, credential.token_id) if credential else None
    owner = session.get(User, token.owner_id) if token else None
    if (not credential or not token or not owner or owner.disabled or token_status(token) != 'active'
        or credential.revoked_at or (credential.retire_at and aware(credential.retire_at) <= utcnow())
        or token.instance_id != instance_id(session)):
        raise unauthorized()
    return token, credential, owner


@dataclass
class ApiPrincipal:
    token_id: str
    credential_id: str
    user: User
    request_id: str

    @property
    def actor(self):
        from types import SimpleNamespace
        return SimpleNamespace(id=self.user.id, username=self.user.username, role=self.user.role, api_token_id=self.token_id)

    def grants(self):
        with Session(get_engine()) as session:
            token, _, owner = load_valid(session, self.credential_id)
            return [ScopeGrant.model_validate(g) for g in json.loads(token.grants_json) if role_allows(owner.role, g['scope'])]

    def allows(self, scope, kind, resource_id, target=None):
        return any(g.scope == scope and g.kind == kind and g.resource_id in {'*', resource_id}
                   and g.target == target for g in self.grants())

    def require(self, scope, kind, resource_id, target=None, *, invisible=False):
        if not self.allows(scope, kind, resource_id, target):
            raise HTTPException(404 if invisible else 403, 'Resource not found' if invisible else 'Insufficient scope')

    def preset_actor(self):
        from app.services.authorization import Grant, Principal
        # The exact request is checked through require() again inside Apply's lock.
        outer = self
        class BoundPrincipal(Principal):
            def require(self, action, *, preset_id=None, target=None):
                outer.require(action, 'preset', preset_id or '*', target, invisible=preset_id is not None)
        grants = tuple(Grant(g.scope, None if g.resource_id == '*' else g.resource_id, g.target)
                       for g in self.grants() if g.kind == 'preset')
        return BoundPrincipal(self.actor, grants)


def require_api(request: Request, _credential=Security(HTTPBearer(auto_error=False, scheme_name="IntegrationToken"))):
    # No cookie fallback, even if a future route accidentally accepts both.
    if request.cookies.get(settings.session_cookie_name):
        raise HTTPException(400, 'Do not combine browser sessions and API tokens')
    authentication_attempt(request.client.host if request.client else 'unknown')
    value = request.headers.get('Authorization', '')
    if len(value) > 512 or not value.startswith('Bearer esrt_'):
        raise unauthorized()
    parts = value.removeprefix('Bearer ').split('_', 2)
    if len(parts) != 3 or len(parts[1]) != 32 or len(parts[2]) < 40:
        raise unauthorized()
    with Session(get_engine(), expire_on_commit=False) as session:
        token, credential, owner = load_valid(session, parts[1])
        if not hmac.compare_digest(credential.secret_hash, hashlib.sha256(parts[2].encode()).hexdigest()):
            raise unauthorized()
        if not credential.last_used_at or (utcnow() - aware(credential.last_used_at)).total_seconds() >= 30:
            credential.last_used_at = utcnow()
            session.add(credential)
            session.commit()
        principal = ApiPrincipal(token.id, credential.id, owner, request.state.api_request_id)
    if request.url.path != '/api/v1/service/stop':
        quota('api:' + principal.token_id, max(1, settings.api_requests_per_minute))
        quota('instance:reads', max(1, settings.api_instance_requests_per_minute))
    maintain_history()
    request.state.api_token_id = principal.token_id
    request.state.api_actor_id = principal.user.id
    return principal


ApiAuth = Depends(require_api)
