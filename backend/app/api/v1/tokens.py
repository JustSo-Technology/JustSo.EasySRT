"""Owner-session token administration. Bearer tokens cannot administer tokens."""
import json
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select
from sqlalchemy import update as sql_update
from app.api.deps import require_owner
from app.core.db import get_session
from app.models.api_token import ApiToken, ApiCredential, ApiAudit
from app.models.auth import User
from app.schemas.api_token import BulkRevoke, TokenCreate, TokenPatch, TokenRotate
from app.services import api_tokens as tokens
from app.services.api_scopes import PRESETS, SCOPES, DESCRIPTIONS, template_grants

router = APIRouter(prefix='/api/v1', tags=['Token administration'], dependencies=[Depends(require_owner)])


def get_token(session, token_id):
    token = session.get(ApiToken, token_id)
    if not token:
        raise HTTPException(404, 'Token not found')
    return token


def writable(session, token_id, revision):
    token = get_token(session, token_id)
    if token.revision != revision:
        raise HTTPException(409, 'Token changed; refresh before editing')
    if tokens.token_status(token) != 'active':
        raise HTTPException(409, 'Expired/revoked tokens cannot be revived; create a replacement')
    return token


@router.get('/token-catalogue')
def catalogue(session: Session = Depends(get_session)):
    identity = tokens.instance_id(session)
    from app.models.site_config import SavedSiteConfigRecord, SavedInputRecord, SavedDestinationRecord
    resources = {'instance': [{'id': identity, 'name': 'This EasySRT instance'}], 'path': [{'id': 'default', 'name': 'Default sender'}]}
    for kind, model in [('preset', SavedSiteConfigRecord), ('input', SavedInputRecord), ('destination', SavedDestinationRecord)]:
        resources[kind] = [{'id': r.id, 'name': r.name} for r in session.exec(select(model).order_by(model.name).limit(1000)).all()]
    from app.api.v1.integration import router as integration_router
    endpoints = {}
    for route in integration_router.routes:
        scope = (route.openapi_extra or {}).get('x-required-scope')
        if scope:
            endpoints.setdefault(scope, []).append(' / '.join(sorted(route.methods)) + ' ' + route.path)
    return {'resources': resources, 'endpoints': endpoints, 'instance_id': identity, 'scopes': [{'id': key, 'group': value[0], 'kind': value[1], 'minimum_role': value[2], 'description': DESCRIPTIONS.get(key, '')} for key, value in SCOPES.items()],
            'presets': [{'id': name, 'version': 1, 'grants': template_grants(name, identity)} for name in PRESETS]}


@router.get('/tokens')
def list_tokens(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                integration: str | None = None, owner_id: str | None = None,
                session: Session = Depends(get_session)):
    query = select(ApiToken).order_by(ApiToken.created_at.desc())
    if integration is not None:
        query = query.where(ApiToken.integration == integration)
    if owner_id is not None:
        query = query.where(ApiToken.owner_id == owner_id)
    return {'items': [tokens.metadata(session, t) for t in session.exec(query.offset(offset).limit(limit)).all()]}


@router.post('/tokens', status_code=201)
def create(payload: TokenCreate, request: Request, session: Session = Depends(get_session), user: User = Depends(require_owner)):
    tokens.quota('manage:' + user.id, 10)
    tokens.reauthenticate(user, payload.current_password)
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    owner = session.get(User, payload.owner_id)
    if not owner or owner.disabled:
        raise HTTPException(422, 'Owning account must be enabled')
    if payload.preset not in PRESETS:
        raise HTTPException(422, 'Unknown preset')
    token = ApiToken(instance_id=tokens.instance_id(session), name=payload.name.strip(), integration=payload.integration.strip(),
                     owner_id=owner.id, creator_id=user.id, grants_json=json.dumps(tokens.validate_grants(session, owner, payload.grants)),
                     expires_at=tokens.validate_expiry(payload.expires_at), preset=payload.preset)
    if not token.name or not token.integration:
        raise HTTPException(422, 'Name and integration cannot be blank')
    canonical = lambda values: {json.dumps(g, sort_keys=True) for g in values}
    token.preset_customized = canonical(json.loads(token.grants_json)) != canonical(template_grants(token.preset, token.instance_id))
    session.add(token)
    secret = tokens.issue_credential(session, token)
    tokens.audit(session, user.id, 'tokens:create', token_id=token.id, request_id=request.state.api_request_id,
                 detail={'grants': json.loads(token.grants_json), 'expires_at': token.expires_at.isoformat()})
    session.commit()
    return {'token': tokens.metadata(session, token), 'secret': secret}


@router.get('/tokens/{token_id}')
def detail(token_id: str, session: Session = Depends(get_session)):
    return tokens.metadata(session, get_token(session, token_id))


@router.patch('/tokens/{token_id}')
def update(token_id: str, payload: TokenPatch, request: Request, session: Session = Depends(get_session), user: User = Depends(require_owner)):
    if payload.grants is not None or payload.expires_at is not None:
        tokens.quota('manage:' + user.id, 10)
        tokens.reauthenticate(user, payload.current_password)
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    token = writable(session, token_id, payload.expected_revision)
    before = {'grants': json.loads(token.grants_json), 'expires_at': tokens.aware(token.expires_at).isoformat(), 'name': token.name}
    if payload.name is not None:
        token.name = payload.name.strip()
        if not token.name:
            raise HTTPException(422, 'Name cannot be blank')
    if payload.grants is not None:
        owner = session.get(User, token.owner_id)
        if not owner or owner.disabled:
            raise HTTPException(409, 'Owning account is disabled')
        token.grants_json = json.dumps(tokens.validate_grants(session, owner, payload.grants))
        token.preset_customized = True
    if payload.expires_at is not None:
        token.expires_at = tokens.validate_expiry(payload.expires_at)
    token.revision += 1
    session.add(token)
    tokens.audit(session, user.id, 'tokens:update', token_id=token.id, request_id=request.state.api_request_id,
                 detail={'before': before, 'after': {'name': token.name, 'grants': json.loads(token.grants_json), 'expires_at': tokens.aware(token.expires_at).isoformat()}})
    session.commit()
    return tokens.metadata(session, token)


@router.post('/tokens/{token_id}/rotate')
def rotate(token_id: str, payload: TokenRotate, request: Request, session: Session = Depends(get_session), user: User = Depends(require_owner)):
    tokens.quota('manage:' + user.id, 10)
    tokens.reauthenticate(user, payload.current_password)
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    token = writable(session, token_id, payload.expected_revision)
    newest = session.exec(select(ApiCredential).where(ApiCredential.token_id == token.id).order_by(ApiCredential.created_at.desc())).first()
    now = tokens.utcnow()
    session.exec(sql_update(ApiCredential).where(ApiCredential.token_id == token.id).values(retire_at=now))
    if newest and not newest.revoked_at:
        newest.retire_at = min(tokens.aware(token.expires_at), now + timedelta(seconds=payload.overlap_seconds))
        session.add(newest)
    secret = tokens.issue_credential(session, token)
    token.revision += 1
    session.add(token)
    tokens.audit(session, user.id, 'tokens:rotate', token_id=token.id, request_id=request.state.api_request_id,
                 detail={'overlap_seconds': payload.overlap_seconds})
    session.commit()
    return {'token': tokens.metadata(session, token), 'secret': secret}


def revoke_tokens(session, ids, user, request_id):
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    targets = [get_token(session, token_id) for token_id in set(ids)]
    for token in targets:
        if token.revoked_at:
            continue
        token.revoked_at = tokens.utcnow()
        token.revision += 1
        session.add(token)
        session.exec(sql_update(ApiCredential).where(ApiCredential.token_id == token.id).values(revoked_at=token.revoked_at))
        tokens.audit(session, user.id, 'tokens:revoke', token_id=token.id, request_id=request_id)
    session.commit()
    return {'revoked_ids': sorted(set(ids))}


@router.post('/tokens/{token_id}/revoke')
def revoke(token_id: str, request: Request, session: Session = Depends(get_session), user: User = Depends(require_owner)):
    return revoke_tokens(session, [token_id], user, request.state.api_request_id)


@router.post('/tokens/revoke')
def bulk(payload: BulkRevoke, request: Request, session: Session = Depends(get_session), user: User = Depends(require_owner)):
    return revoke_tokens(session, payload.ids, user, request.state.api_request_id)


@router.get('/tokens/{token_id}/audit-events')
def history(token_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session: Session = Depends(get_session)):
    get_token(session, token_id)
    rows = session.exec(select(ApiAudit).where(ApiAudit.token_id == token_id).order_by(ApiAudit.created_at.desc()).offset(offset).limit(limit)).all()
    return {'items': [r.model_dump(mode='json') for r in rows]}
