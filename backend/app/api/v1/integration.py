"""Versioned, bearer-only external API. No direct site activation bypass."""
import hashlib
import json
import platform
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from app.core.db import get_engine, get_session
from app.models.api_token import ApiAudit, ApiCommand
from app.models.site_config import SavedSiteConfigRecord, SavedInputRecord, SavedDestinationRecord
from app.schemas.config import AppConfig, SiteConfig, InputSource, Destination, ApplyPresetRequest
from app.services import api_tokens as tokens, config_service as config, config_transfer as transfer
from app.services.api_tokens import ApiAuth, ApiPrincipal
from app.services.api_scopes import SCOPES, PRESETS, template_grants
from app.services.api_redaction import redact, source_view, merge_source, has_secret
from app.services.config_snapshots import apply_preset, target_lock, read_app_settings, durable_write, digest
from app.core.settings import settings
from app.version import APP_VERSION

router = APIRouter(prefix='/api/v1', tags=['Integration API'])


def operation(path, method, scope=None, kind=None, **kwargs):
    return router.api_route(path, methods=[method], openapi_extra={'x-required-scope': scope, 'x-resource-kind': kind}, **kwargs)


def identity():
    with Session(get_engine()) as session:
        return tokens.instance_id(session)


def instance_scope(p, scope):
    p.require(scope, 'instance', identity())


def event(p, scope, resource, outcome='success'):
    with Session(get_engine()) as session:
        tokens.audit(session, p.user.id, scope, token_id=p.token_id, resource_id=resource,
                     request_id=p.request_id, outcome=outcome)
        session.commit()


def observed(p):
    from app.services.service_control import _read_service_state
    from app.services.sender_health import read_sender_health
    state, _, helper = _read_service_state(p.actor)
    health = read_sender_health(state, helper)
    # No preflight/network probes or raw logs on monitoring scrapes.
    return {'instance_id': identity(), 'path_id': 'default', 'service_state': state,
            'media': {k: v for k, v in health.model_dump(mode='json').items() if k in {
                'state', 'reason', 'run_id', 'config_id', 'snapshot_id', 'input', 'output', 'retry_count',
                'attempt', 'next_retry_at', 'last_failure_at', 'last_recovery_at', 'heartbeat_at',
                'remote_receipt', 'desired_running', 'pending_config'}},
            'events': redact(health.events)}


@operation('/', 'GET')
def discovery(p: ApiPrincipal = ApiAuth):
    return {'api_version': 'v1', 'app_version': APP_VERSION, 'instance_id': identity(),
            'features': {'media_health': True, 'durable_health_history': False, 'multiple_paths': False,
                         'token_delegation': False, 'notification_service': False, 'api_update_install': False}}


@operation('/auth/token', 'GET')
def own_token(p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    from app.models.api_token import ApiToken
    token = session.get(ApiToken, p.token_id)
    return {'id': token.id, 'name': token.name, 'integration': token.integration, 'expires_at': token.expires_at,
            'instance_id': token.instance_id, 'effective_grants': [g.model_dump() for g in p.grants()]}


@operation('/scopes', 'GET')
def scopes(p: ApiPrincipal = ApiAuth):
    return {'items': [{'id': k, 'group': v[0], 'kind': v[1], 'minimum_role': v[2]} for k, v in SCOPES.items()]}


@operation('/scope-presets', 'GET')
def presets_catalogue(p: ApiPrincipal = ApiAuth):
    return {'items': [{'id': k, 'version': 1, 'grants': template_grants(k, identity())} for k in PRESETS]}


@operation('/service/status', 'GET', 'service:read', 'path')
def service_status(p: ApiPrincipal = ApiAuth):
    p.require('service:read', 'path', 'default')
    result = observed(p)
    result.pop('events')
    from app.models.site_config import SelectedConfigState
    with Session(get_engine()) as session:
        selected = session.get(SelectedConfigState, 'default')
        result['selected_id'] = selected.snapshot_id if selected else None
    state_actions = ('stop', 'restart') if result['service_state'] == 'active' else ('stop',) if result['service_state'] in {'activating', 'deactivating'} else ('start',) if result['service_state'] in {'inactive', 'failed'} else ()
    result['allowed_actions'] = [a for a in state_actions if p.allows('service:' + a, 'path', 'default')]
    return result


@operation('/health', 'GET', 'health:read', 'path')
@operation('/paths/default/health', 'GET', 'health:read', 'path')
def health(p: ApiPrincipal = ApiAuth):
    p.require('health:read', 'path', 'default')
    return {k: v for k, v in observed(p).items() if k != 'events'}


@operation('/paths', 'GET', 'health:read', 'path')
def paths(p: ApiPrincipal = ApiAuth):
    p.require('health:read', 'path', 'default')
    return {'items': [{'id': 'default'}]}


@operation('/health/events', 'GET', 'health-events:read', 'path')
@operation('/paths/default/events', 'GET', 'health-events:read', 'path')
def health_events(limit: int = Query(20, ge=1, le=20), p: ApiPrincipal = ApiAuth):
    p.require('health-events:read', 'path', 'default')
    return {'items': observed(p)['events'][-limit:], 'durable': False, 'retention': 'current supervisor run; at most 20 events'}


@operation('/metrics', 'GET', 'metrics:read', 'path', response_class=PlainTextResponse)
def metrics(p: ApiPrincipal = ApiAuth):
    p.require('metrics:read', 'path', 'default')
    media = observed(p)['media']
    lines = ['# TYPE easysrt_media_healthy gauge', f'easysrt_media_healthy {int(media["state"] == "healthy")}',
             '# TYPE easysrt_health_known gauge', f'easysrt_health_known {int(media["state"] != "unknown")}',
             '# TYPE easysrt_retry_count gauge', f'easysrt_retry_count {media["retry_count"]}']
    for side in ('input', 'output'):
        age = media[side]['age_seconds']
        if age is not None:
            lines.append(f'easysrt_media_age_seconds{{side="{side}"}} {age}')
    return '\n'.join(lines) + '\n'


class CommandBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_selection_id: str | None = None


def command(action, body, request, p):
    from app.services.service_control import perform_service_action, ServiceCommandFailure
    p.require('service:' + action, 'path', 'default')
    key = request.headers.get('Idempotency-Key', '')
    if not 1 <= len(key) <= 100:
        raise HTTPException(428, 'Idempotency-Key (1-100 characters) is required')
    fingerprint = digest({'action': action, 'body': body.model_dump(), 'path': 'default'})
    command_id = hashlib.sha256((p.token_id + ':' + key).encode()).hexdigest()
    tokens.quota('command:' + p.token_id, max(1, settings.api_commands_per_minute))
    tokens.quota('instance:commands', max(1, settings.api_instance_commands_per_minute))
    with target_lock():
        p.require('service:' + action, 'path', 'default')
        with Session(get_engine()) as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            previous = session.get(ApiCommand, command_id)
            if previous:
                if previous.request_hash != fingerprint:
                    raise HTTPException(409, 'Idempotency key was used for another command')
                if previous.status != 'done':
                    raise HTTPException(409, 'Command outcome is pending/unknown; reconcile status before another command')
                return json.loads(previous.result_json)
            session.add(ApiCommand(id=command_id, token_id=p.token_id, request_hash=fingerprint))
            tokens.audit(session, p.user.id, 'service:' + action, token_id=p.token_id, resource_id='default',
                         request_id=p.request_id, outcome='dispatching')
            session.commit()
        try:
            perform_service_action(action, p.actor, expected_selection_id=body.expected_selection_id)
        except (HTTPException, ServiceCommandFailure) as exc:
            event(p, 'service:' + action, 'default', 'failed')
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(exc.status_code, 'Sender command failed; reconcile service status') from None
        result = {'action': action, 'completed': True, 'request_id': p.request_id}
        with Session(get_engine()) as session:
            row = session.get(ApiCommand, command_id)
            row.status, row.result_json = 'done', json.dumps(result)
            session.add(row)
            tokens.audit(session, p.user.id, 'service:' + action, token_id=p.token_id, resource_id='default', request_id=p.request_id)
            session.commit()
        return result


def command_route(action):
    def run(body: CommandBody, request: Request, p: ApiPrincipal = ApiAuth):
        return command(action, body, request, p)
    run.__name__ = 'service_' + action
    operation('/service/' + action, 'POST', 'service:' + action, 'path')(run)


for _action in ('start', 'stop', 'restart'):
    command_route(_action)


@operation('/system', 'GET', 'system:read', 'instance')
def system(p: ApiPrincipal = ApiAuth):
    instance_scope(p, 'system:read')
    return {'instance_id': identity(), 'app_version': APP_VERSION, 'platform': platform.system()}


@operation('/diagnostics', 'GET', 'diagnostics:read', 'path')
def diagnostics(p: ApiPrincipal = ApiAuth):
    p.require('diagnostics:read', 'path', 'default')
    return {'passive_observation': observed(p), 'active_probe': '/api/v1/diagnostics/run'}


@operation('/diagnostics/run', 'POST', 'diagnostics:run', 'path')
def run_diagnostics(p: ApiPrincipal = ApiAuth):
    from app.services.diagnostics import get_diagnostics
    p.require('diagnostics:run', 'path', 'default')
    tokens.quota('probe:' + p.token_id, 6)
    result = redact(get_diagnostics().model_dump(mode='json'))
    event(p, 'diagnostics:run', 'default')
    return result


@operation('/logs', 'GET', 'logs:read', 'path')
def logs(p: ApiPrincipal = ApiAuth):
    from app.services.service_control import get_recent_logs
    p.require('logs:read', 'path', 'default')
    tokens.quota('logs:' + p.token_id, 12)
    return {'lines': redact(get_recent_logs(p.actor))}


def site_view(site, p, kind, resource):
    value = site.model_dump() if isinstance(site, SiteConfig) else site.copy()
    return {**value, 'input': source_view(value['input'], p, kind, resource)}


@operation('/config', 'GET', 'config:read', 'instance')
def read_config(p: ApiPrincipal = ApiAuth):
    instance_scope(p, 'config:read')
    with target_lock():
        bundle = config.load_bundle()
        current_app = read_app_settings()
    return {'app': current_app, 'app_digest': digest(current_app.model_dump()), 'site': site_view(bundle.site, p, 'instance', identity()), 'selected': bundle.selected}


class AppUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    app: AppConfig
    expected_digest: str


@operation('/config/app', 'PATCH', 'config-app:update', 'instance')
def update_app(body: AppUpdate, p: ApiPrincipal = ApiAuth):
    instance_scope(p, 'config-app:update')
    with target_lock():
        instance_scope(p, 'config-app:update')
        if digest(read_app_settings().model_dump()) != body.expected_digest:
            raise HTTPException(409, 'App settings changed; review again')
        durable_write(settings.app_config_path, body.app.model_dump_json())
    event(p, 'config-app:update', identity())
    return {'app': body.app, 'digest': digest(body.app.model_dump()), 'selected_configuration_changed': False}


@operation('/config/validate', 'POST', 'config:validate', 'instance')
def validate_site(site: SiteConfig, p: ApiPrincipal = ApiAuth):
    instance_scope(p, 'config:validate')
    return {'valid': True}


class PresetBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=120)
    site: dict | None = None
    expected_revision: int | None = Field(default=None, ge=1)


def get_preset(session, p, preset_id, scope='presets:read'):
    p.require(scope, 'preset', preset_id, invisible=True)
    return config.get_preset(session, preset_id)


@operation('/presets', 'GET', 'presets:read', 'preset')
def list_presets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    grants = [g for g in p.grants() if g.scope == 'presets:read']
    if not grants:
        raise HTTPException(403, 'Insufficient scope')
    query = select(SavedSiteConfigRecord).order_by(SavedSiteConfigRecord.id)
    if not any(g.resource_id == '*' for g in grants):
        query = query.where(SavedSiteConfigRecord.id.in_([g.resource_id for g in grants]))
    return {'items': [config._saved_config_summary(r) for r in session.exec(query.offset(offset).limit(limit)).all()]}


@operation('/presets/{preset_id}', 'GET', 'presets:read', 'preset')
def preset_detail(preset_id: str, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    record = get_preset(session, p, preset_id)
    view = config.preview_preset(session, preset_id).model_dump(mode='json')
    view['bundle'] = {'app': view['bundle']['app'], 'site': site_view(view['bundle']['site'], p, 'preset', record.id)}
    return view


@operation('/presets', 'POST', 'presets:create', 'preset', status_code=201)
def create_preset(body: PresetBody, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    p.require('presets:create', 'preset', '*')
    if not body.name or not body.name.strip() or body.site is None:
        raise HTTPException(422, 'Name and site are required')
    site = body.site.copy()
    site['input'] = merge_source(site.get('input', {}), None, p, 'preset', '*')
    model = SiteConfig.model_validate(site)
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    try:
        record = config.save_named_site_config(session, body.name, model, p.user.id)
        tokens.audit(session, p.user.id, 'presets:create', token_id=p.token_id, resource_id=record.id, request_id=p.request_id)
        session.commit()
    except IntegrityError:
        raise HTTPException(409, 'Preset name conflict') from None
    return record


@operation('/presets/{preset_id}', 'PATCH', 'presets:update', 'preset')
def update_preset(preset_id: str, body: PresetBody, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    p.require('presets:update', 'preset', preset_id, invisible=True)
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    record = config.get_preset(session, preset_id)
    config.check_revision(record, body.expected_revision)
    if body.site is not None:
        site = body.site.copy()
        old = json.loads(record.site_payload)
        site['input'] = merge_source(site.get('input', {}), old['input'], p, 'preset', preset_id)
        config.update_saved_site_config(session, preset_id, SiteConfig.model_validate(site), record.revision)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, 'Preset name cannot be blank')
        config.rename_saved_site_config(session, preset_id, body.name, record.revision)
    tokens.audit(session, p.user.id, 'presets:update', token_id=p.token_id, resource_id=preset_id, request_id=p.request_id)
    session.commit()
    return config._saved_config_summary(record)


@operation('/presets/{preset_id}', 'DELETE', 'presets:delete', 'preset')
def delete_preset(preset_id: str, expected_revision: int, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    p.require('presets:delete', 'preset', preset_id, invisible=True)
    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
    config.delete_saved_site_config(session, preset_id, expected_revision)
    tokens.audit(session, p.user.id, 'presets:delete', token_id=p.token_id, resource_id=preset_id, request_id=p.request_id)
    session.commit()
    return {'deleted': True}


@operation('/presets/{preset_id}/apply', 'POST', 'presets:apply', 'preset')
def apply(preset_id: str, body: ApplyPresetRequest, p: ApiPrincipal = ApiAuth):
    p.require('presets:apply', 'preset', preset_id, body.target, invisible=True)
    # Bind replay IDs to the credential owner AND logical token, not merely user.
    body.request_id = hashlib.sha256((p.token_id + ':' + body.request_id).encode()).hexdigest()
    bundle = apply_preset(p.preset_actor(), preset_id, body)
    event(p, 'presets:apply', preset_id)
    return {'selected': bundle.selected, 'running_sender_restarted': False}


LIBRARIES = {'inputs': (SavedInputRecord, 'input_payload', InputSource, 'input'),
             'destinations': (SavedDestinationRecord, 'destination_payload', Destination, 'destination')}


def library_routes(prefix):
    model, field, schema, kind = LIBRARIES[prefix]
    def view(record, p):
        value = json.loads(getattr(record, field))
        if kind == 'input':
            value = source_view(value, p, kind, record.id)
        return {'id': record.id, 'value': value, 'digest': digest(json.loads(getattr(record, field))),
                'created_at': record.created_at, 'updated_at': record.updated_at}

    def get(session, p, resource_id, action):
        p.require(prefix + ':' + action, kind, resource_id, invisible=True)
        record = session.get(model, resource_id)
        if not record:
            raise HTTPException(404, 'Resource not found')
        return record

    def listing(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
        grants = [g for g in p.grants() if g.scope == prefix + ':read']
        if not grants:
            raise HTTPException(403, 'Insufficient scope')
        query = select(model).order_by(model.id)
        if not any(g.resource_id == '*' for g in grants):
            query = query.where(model.id.in_([g.resource_id for g in grants]))
        return {'items': [view(r, p) for r in session.exec(query.offset(offset).limit(limit)).all()]}

    def detail(resource_id: str, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
        return view(get(session, p, resource_id, 'read'), p)

    def create(body: dict, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
        p.require(prefix + ':create', kind, '*')
        value = body.get('value', {})
        if kind == 'input':
            value = merge_source(value, None, p, kind, '*')
        parsed = schema.model_validate(value)
        if not parsed.name.strip() or len(parsed.name) > 120:
            raise HTTPException(422, 'Name must be 1-120 characters')
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        record = model(name=parsed.name, **{field: parsed.model_dump_json()})
        session.add(record)
        tokens.audit(session, p.user.id, prefix + ':create', token_id=p.token_id, resource_id=record.id, request_id=p.request_id)
        try:
            session.commit()
        except IntegrityError:
            raise HTTPException(409, 'Resource name conflict') from None
        return {'id': record.id, 'digest': digest(parsed.model_dump())}

    def update(resource_id: str, body: dict, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
        p.require(prefix + ':update', kind, resource_id, invisible=True)
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        record = session.get(model, resource_id)
        if not record:
            raise HTTPException(404, 'Resource not found')
        old = json.loads(getattr(record, field))
        if body.get('expected_digest') != digest(old):
            raise HTTPException(409, 'Resource changed; review its digest again')
        value = body.get('value', {})
        if kind == 'input':
            value = merge_source(value, old, p, kind, resource_id)
        parsed = schema.model_validate(value)
        if not parsed.name.strip() or len(parsed.name) > 120:
            raise HTTPException(422, 'Name must be 1-120 characters')
        setattr(record, field, parsed.model_dump_json())
        record.name, record.updated_at = parsed.name, tokens.utcnow()
        session.add(record)
        tokens.audit(session, p.user.id, prefix + ':update', token_id=p.token_id, resource_id=resource_id, request_id=p.request_id)
        try:
            session.commit()
        except IntegrityError:
            raise HTTPException(409, 'Resource name conflict') from None
        return {'id': record.id, 'digest': digest(parsed.model_dump())}

    def delete(resource_id: str, expected_digest: str, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
        p.require(prefix + ':delete', kind, resource_id, invisible=True)
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        record = session.get(model, resource_id)
        if not record:
            raise HTTPException(404, 'Resource not found')
        if expected_digest != digest(json.loads(getattr(record, field))):
            raise HTTPException(409, 'Resource changed; review its digest again')
        session.delete(record)
        tokens.audit(session, p.user.id, prefix + ':delete', token_id=p.token_id, resource_id=resource_id, request_id=p.request_id)
        session.commit()
        return {'deleted': True}

    for path, method, action, handler in [('', 'GET', 'read', listing), ('/{resource_id}', 'GET', 'read', detail),
            ('', 'POST', 'create', create), ('/{resource_id}', 'PATCH', 'update', update), ('/{resource_id}', 'DELETE', 'delete', delete)]:
        handler.__name__ = prefix + '_' + handler.__name__
        operation('/' + prefix + path, method, prefix + ':' + action, kind)(handler)


for _library in LIBRARIES:
    library_routes(_library)


@operation('/config/export', 'GET', 'config:export', 'instance')
def export_config(p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    instance_scope(p, 'config:export')
    doc = {'format': transfer.FORMAT, 'schema_version': 1, 'source': {'app_version': APP_VERSION},
           'exported_at': tokens.utcnow().isoformat()}
    redacted_secrets = False
    for plural, model, field, kind in [('presets', SavedSiteConfigRecord, 'site_payload', 'preset'),
            ('inputs', SavedInputRecord, 'input_payload', 'input'), ('destinations', SavedDestinationRecord, 'destination_payload', 'destination')]:
        grants = [g.resource_id for g in p.grants() if g.scope == plural + ':read']
        query = select(model).order_by(model.id)
        if '*' not in grants:
            query = query.where(model.id.in_(grants))
        values = []
        for record in session.exec(query.limit(501)).all():
            value = json.loads(getattr(record, field))
            if kind == 'preset':
                value = {'name': record.name, 'site': site_view(value, p, kind, record.id)}
                redacted_secrets |= value['site']['input'].pop('url_has_secret', False)
            elif kind == 'input':
                value = source_view(value, p, kind, record.id)
                redacted_secrets |= value.pop('url_has_secret', False)
            values.append(value)
        doc[plural] = values
    if p.allows('config:read', 'instance', identity()):
        bundle = config.load_bundle()
        site = site_view(bundle.site, p, 'instance', identity())
        redacted_secrets |= site['input'].pop('url_has_secret', False)
        doc['current'] = {'name': 'Imported current configuration', 'site': site}
        doc['station'] = bundle.app.model_dump()
    if sum(len(doc[key]) for key in ('presets', 'inputs', 'destinations')) > 500 or len(json.dumps(doc).encode()) > 524288:
        raise HTTPException(413, 'Export exceeds portable limits; narrow its resource scope')
    return {'document': doc, 'secrets_redacted': redacted_secrets}


class ImportAuthorization:
    def __init__(self, p, session):
        self.p, self.session = p, session

    def authorize_import_items(self, items):
        p = self.p
        for item in items:
            if item['action'] == 'skip':
                continue
            plural = {'preset': 'presets', 'input': 'inputs', 'destination': 'destinations'}[item['kind']]
            p.require(plural + (':update' if item['target_id'] else ':create'), item['kind'], item['target_id'] or '*')
            if item['kind'] not in {'preset', 'input'}:
                continue
            value = item['payload']['input'] if item['kind'] == 'preset' else item['payload']
            model = SavedSiteConfigRecord if item['kind'] == 'preset' else SavedInputRecord
            old = self.session.get(model, item['target_id']) if item['target_id'] else None
            payload = json.loads(getattr(old, 'site_payload' if item['kind'] == 'preset' else 'input_payload')) if old else None
            old_source = payload['input'] if payload and item['kind'] == 'preset' else payload
            preserved = merge_source(value, old_source, p, item['kind'], item['target_id'] or '*')
            value.update(preserved)


def transfer_checks(p, scope):
    instance_scope(p, scope)
    # Collection-wide previews inspect conflict metadata for all saved objects.
    for action, kind in [('presets:read', 'preset'), ('inputs:read', 'input'), ('destinations:read', 'destination')]:
        p.require(action, kind, '*')


@operation('/config/import/preview', 'POST', 'config-import:preview', 'instance')
def import_preview(body: transfer.ImportRequest, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    transfer_checks(p, 'config-import:preview')
    return transfer.preview(session, body, p.user, ImportAuthorization(p, session), token_id=p.token_id)


@operation('/config/import', 'POST', 'config:import', 'instance')
def import_commit(body: transfer.ImportRequest, p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    transfer_checks(p, 'config:import')
    # The legacy importer owns BEGIN IMMEDIATE; release this read transaction first.
    session.rollback()
    result = transfer.commit_import(session, body, p.user, ImportAuthorization(p, session), token_id=p.token_id)
    event(p, 'config:import', identity())
    return result


@operation('/redundancy/status', 'GET', 'redundancy:read', 'instance')
def redundancy(p: ApiPrincipal = ApiAuth):
    from app.services.redundancy import get_redundancy_status
    instance_scope(p, 'redundancy:read')
    return redact(get_redundancy_status().model_dump(mode='json'))


@operation('/redundancy/config-sync', 'GET', 'config-sync:read', 'instance')
def config_sync(p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    from app.models.redundancy import ReplicatedConfigState, PartnerSyncState
    instance_scope(p, 'config-sync:read')
    state = session.get(ReplicatedConfigState, 'default')
    partner = session.get(PartnerSyncState, 'partner')
    return {'current_version': state.current_version if state else None,
            'partner_sync_state': partner.sync_state if partner else 'not_configured',
            'last_acked_version': partner.last_acked_version if partner else None,
            'runtime_validation_state': partner.runtime_validation_state if partner else 'unknown',
            'takeover_eligibility': partner.takeover_eligibility if partner else 'unknown'}


@operation('/updates/status', 'GET', 'updates:read', 'instance')
def updates(p: ApiPrincipal = ApiAuth):
    from app.services.update_manager import get_update_status
    instance_scope(p, 'updates:read')
    result = get_update_status().model_dump(mode='json')
    return {k: v for k, v in result.items() if k in {'installed_commit', 'latest_commit', 'update_available', 'checked_at', 'job_status'}}


@operation('/updates/check', 'POST', 'updates:check', 'instance')
def check_updates(p: ApiPrincipal = ApiAuth):
    from app.services.update_manager import check_for_updates
    instance_scope(p, 'updates:check')
    tokens.quota('update:' + p.token_id, 2)
    result = check_for_updates().model_dump(mode='json')
    event(p, 'updates:check', identity())
    return {k: v for k, v in result.items() if k in {'installed_commit', 'latest_commit', 'update_available', 'checked_at', 'job_status'}}


@operation('/audit-events', 'GET', 'audit:read', 'instance')
def audit_events(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), p: ApiPrincipal = ApiAuth, session: Session = Depends(get_session)):
    instance_scope(p, 'audit:read')
    return {'items': [r.model_dump(mode='json') for r in session.exec(select(ApiAudit).order_by(ApiAudit.created_at.desc()).offset(offset).limit(limit)).all()]}


@operation('/openapi.json', 'GET')
def specification(p: ApiPrincipal = ApiAuth):
    from fastapi.openapi.utils import get_openapi
    return get_openapi(title='EasySRT Integration API', version='1.0.0', routes=router.routes,
                       description='HTTPS and scoped bearer credentials required. x-required-scope and x-resource-kind describe each operation.')
