"""Real credential/session/CSRF requests; no authentication dependency overrides."""
from datetime import timedelta
import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.core.db import get_engine
from app.models.api_token import ApiCredential, ApiToken, ApiAudit
from app.models.auth import User
from app.services.api_scopes import SCOPES, template_grants
from app.services.api_tokens import utcnow
from app.services.config_service import load_bundle

PASSWORD = 'scoped-api-test-password'


@pytest.fixture
def owner():
    from app.services.api_tokens import _attempts
    _attempts.clear()
    with TestClient(app, base_url='https://testserver') as client:
        login = client.post('/api/auth/bootstrap-owner', json={'username': 'owner', 'password': PASSWORD, 'role': 'owner'})
        assert login.status_code == 200, login.text
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        yield client, login.json()['user']['id']


def issue(owner, grants=None, preset='monitor', owner_id=None):
    client, user_id = owner
    identity = client.get('/api/v1/token-catalogue').json()['instance_id']
    response = client.post('/api/v1/tokens', json={'name': 'Integration test', 'integration': 'tests', 'owner_id': owner_id or user_id,
        'expires_at': (utcnow() + timedelta(days=90)).isoformat(), 'current_password': PASSWORD,
        'preset': preset, 'grants': grants if grants is not None else template_grants(preset, identity)})
    assert response.status_code == 201, response.text
    return response.json()


def grant(scope, kind, resource='*', target=None):
    return {'scope': scope, 'kind': kind, 'resource_id': resource, 'target': target}


def bearer(secret, secure=True):
    client = TestClient(app, base_url=('https' if secure else 'http') + '://testserver')
    client.headers['Authorization'] = 'Bearer ' + secret
    return client


def saved(owner, name='Preset', url='https://source.example/live'):
    site = load_bundle().site.model_dump()
    site['input']['url'] = url
    r = owner[0].post('/api/config/saved', json={'name': name, 'site': site})
    assert r.status_code == 200, r.text
    return r.json()['saved_config']


def test_secret_shown_once_hashed_and_metadata_only(owner):
    result = issue(owner)
    secret, token = result['secret'], result['token']
    listing = owner[0].get('/api/v1/tokens')
    assert secret not in listing.text
    assert 'secret_hash' not in listing.text
    assert listing.headers['cache-control'] == 'no-store'
    with Session(get_engine()) as session:
        credential = session.exec(select(ApiCredential)).first()
        assert credential.secret_hash not in secret
        assert len(credential.secret_hash) == 64
        assert secret not in str(session.exec(select(ApiAudit)).all())
    client = bearer(secret)
    assert client.get('/api/v1/').status_code == 200
    own = client.get('/api/v1/auth/token').json()
    assert own['id'] == token['id']
    assert owner[0].get('/api/v1/tokens/' + token['id']).json()['last_used_at']


@pytest.mark.parametrize('route', ['/api/config', '/api/service/status', '/api/auth/users', '/api/update/launch', '/api/v1/tokens', '/api/v1/token-catalogue'])
def test_bearer_cannot_enter_browser_or_management_routes(owner, route):
    token = issue(owner)
    assert bearer(token['secret']).get(route).status_code == 401


def test_https_mixed_cookie_and_csrf_boundaries(owner):
    result = issue(owner)
    assert bearer(result['secret'], secure=False).get('/api/v1/health').status_code == 400
    client = bearer(result['secret'])
    client.cookies.update(owner[0].cookies)
    assert client.get('/api/v1/health').status_code == 400
    assert owner[0].get('/api/v1/health').status_code == 400
    owner[0].headers.pop('X-CSRF-Token')
    assert owner[0].post('/api/v1/tokens/' + result['token']['id'] + '/revoke').status_code == 403


def test_monitor_has_no_stream_or_library_write(owner):
    token = issue(owner)
    client = bearer(token['secret'])
    assert client.get('/api/v1/health').status_code == 200
    assert client.get('/api/v1/metrics').status_code == 200
    assert client.post('/api/v1/service/stop', json={}, headers={'Idempotency-Key': 'stop1'}).status_code == 403
    assert client.get('/api/v1/config').status_code == 403
    assert client.post('/api/v1/presets', json={'name': 'X', 'site': load_bundle().site.model_dump()}).status_code == 403


def test_resource_lists_filter_before_pagination_and_edit_does_not_apply(owner):
    a, b = saved(owner, 'A'), saved(owner, 'B')
    token = issue(owner, [grant('presets:read', 'preset', b['id']), grant('presets:update', 'preset', b['id'])])
    client = bearer(token['secret'])
    items = client.get('/api/v1/presets?limit=1').json()['items']
    assert [i['id'] for i in items] == [b['id']]
    assert client.get('/api/v1/presets/' + a['id']).status_code == 404
    changed = client.patch('/api/v1/presets/' + b['id'], json={'name': 'B2', 'expected_revision': 1})
    assert changed.status_code == 200, changed.text
    assert load_bundle().selected is None
    assert client.post('/api/v1/presets/' + b['id'] + '/apply', json={'request_id': 'apply'}).status_code == 404


def test_secret_redacted_projection_preserves_credentials(owner):
    a = saved(owner, url='https://alice:private-password@source.example/live?token=private-token')
    token = issue(owner, [grant('presets:read', 'preset', a['id']), grant('presets:update', 'preset', a['id'])])
    client = bearer(token['secret'])
    detail = client.get('/api/v1/presets/' + a['id'])
    assert 'private-password' not in detail.text and 'private-token' not in detail.text
    site = detail.json()['bundle']['site']
    site['profile']['name'] = 'Changed profile'
    response = client.patch('/api/v1/presets/' + a['id'], json={'site': site, 'expected_revision': 1})
    assert response.status_code == 200, response.text
    source = owner[0].get('/api/config/saved/' + a['id']).json()['bundle']['site']['input']['url']
    assert 'private-password' in source and 'private-token' in source
    site['input']['url'] = 'https://new-password@another.example/feed'
    denied = client.patch('/api/v1/presets/' + a['id'], json={'site': site, 'expected_revision': 2})
    assert denied.status_code == 403, denied.text
    assert 'new-password' not in denied.text


def test_revocation_expiry_wrong_secret_and_owner_disable(owner):
    token = issue(owner)
    client = bearer(token['secret'])
    assert bearer(token['secret'][:-1] + '!').get('/api/v1/').status_code == 401
    owner[0].post('/api/v1/tokens/' + token['token']['id'] + '/revoke')
    assert client.get('/api/v1/').status_code == 401
    second = issue(owner)
    with Session(get_engine()) as session:
        record = session.get(ApiToken, second['token']['id'])
        record.expires_at = utcnow() - timedelta(seconds=1)
        session.add(record)
        session.commit()
    assert bearer(second['secret']).get('/api/v1/').status_code == 401
    third = issue(owner)
    with Session(get_engine()) as session:
        user = session.get(User, owner[1])
        user.disabled = True
        session.add(user)
        session.commit()
    assert bearer(third['secret']).get('/api/v1/').status_code == 401


def test_rotation_overlap_shared_permissions_and_revoke(owner):
    first = issue(owner)
    token_id = first['token']['id']
    second = owner[0].post(f'/api/v1/tokens/{token_id}/rotate', json={'expected_revision': 1, 'overlap_seconds': 3600, 'current_password': PASSWORD})
    assert second.status_code == 200, second.text
    assert bearer(first['secret']).get('/api/v1/health').status_code == 200
    assert bearer(second.json()['secret']).get('/api/v1/health').status_code == 200
    third = owner[0].post(f'/api/v1/tokens/{token_id}/rotate', json={'expected_revision': 2, 'overlap_seconds': 3600, 'current_password': PASSWORD}).json()
    assert bearer(first['secret']).get('/api/v1/').status_code == 401
    assert bearer(second.json()['secret']).get('/api/v1/').status_code == 200
    owner[0].post(f'/api/v1/tokens/{token_id}/revoke')
    assert bearer(third['secret']).get('/api/v1/').status_code == 401
    assert bearer(second.json()['secret']).get('/api/v1/').status_code == 401


def test_role_ceiling_rechecked_and_preset_cannot_expand(owner):
    token = issue(owner, [grant('presets:create', 'preset'), grant('health:read', 'path', 'default')])
    with Session(get_engine()) as session:
        user = session.get(User, owner[1]); user.role = 'operator'; session.add(user); session.commit()
    client = bearer(token['secret'])
    assert client.get('/api/v1/health').status_code == 200
    assert client.post('/api/v1/presets', json={'name': 'No', 'site': load_bundle().site.model_dump()}).status_code == 403
    assert client.get('/api/v1/auth/token').json()['effective_grants'] == [grant('health:read', 'path', 'default')]


def test_token_mutation_requires_revision_and_password(owner):
    first = issue(owner)
    path = '/api/v1/tokens/' + first['token']['id']
    assert owner[0].patch(path, json={'name': 'Named', 'expected_revision': 20}).status_code == 409
    assert owner[0].patch(path, json={'expires_at': (utcnow() + timedelta(days=180)).isoformat(), 'expected_revision': 1}).status_code == 403
    assert owner[0].patch(path, json={'name': 'Named', 'expected_revision': 1}).status_code == 200
    owner[0].post(path + '/revoke')
    assert owner[0].patch(path, json={'name': 'Revive', 'expected_revision': 3}).status_code == 409


def test_validation_does_not_echo_password_or_bearer(owner):
    client, user_id = owner
    response = client.post('/api/v1/tokens', json={'name': 'Test', 'owner_id': user_id, 'current_password': 'do-not-echo', 'grants': [{'scope': 'admin:*'}]})
    assert response.status_code == 422
    assert 'do-not-echo' not in response.text
    token = issue(owner)
    bad = bearer(token['secret']).post('/api/v1/config/validate', json={'input': {'url': 'https://private-secret@host/'}})
    assert bad.status_code == 422 and 'private-secret' not in bad.text


def test_stop_only_and_replay_do_not_repeat_command(owner, monkeypatch):
    from app.services import service_control
    calls = []
    monkeypatch.setattr(service_control, 'perform_service_action', lambda *a, **k: calls.append(a[0]))
    token = issue(owner, [grant('service:stop', 'path', 'default')])
    client = bearer(token['secret'])
    first = client.post('/api/v1/service/stop', json={}, headers={'Idempotency-Key': 'once'})
    assert first.status_code == 200, first.text
    assert client.post('/api/v1/service/stop', json={}, headers={'Idempotency-Key': 'once'}).json() == first.json()
    assert calls == ['stop']
    assert client.post('/api/v1/service/restart', json={}, headers={'Idempotency-Key': 'once'}).status_code == 403
    owner[0].post('/api/v1/tokens/' + token['token']['id'] + '/revoke')
    assert client.post('/api/v1/service/stop', json={}, headers={'Idempotency-Key': 'once'}).status_code == 401


def test_route_catalogue_covers_every_integration_operation():
    from app.api.v1.integration import router
    baseline = {'/api/v1/', '/api/v1/auth/token', '/api/v1/scopes', '/api/v1/scope-presets', '/api/v1/openapi.json'}
    for route in router.routes:
        assert route.path in baseline or route.openapi_extra['x-required-scope'] in SCOPES
        assert route.dependant.dependencies, route.path


def test_apply_only_token_checks_source_target_and_cannot_restart(owner):
    a, b = saved(owner, 'A'), saved(owner, 'B')
    detail = owner[0].get('/api/config/saved/' + a['id']).json()
    body = {k: detail[k] for k in ('expected_selection_id', 'app_digest', 'runtime_digest', 'runtime_version')}
    body.update(expected_revision=1, target='default', request_id='reviewed')
    token = issue(owner, [grant('presets:apply', 'preset', a['id'], 'default')])
    client = bearer(token['secret'])
    assert client.get('/api/v1/presets/' + a['id']).status_code == 404
    result = client.post('/api/v1/presets/' + a['id'] + '/apply', json=body)
    assert result.status_code == 200, result.text
    assert result.json()['running_sender_restarted'] is False
    assert client.post('/api/v1/presets/' + b['id'] + '/apply', json=body).status_code == 404
    assert client.post('/api/v1/service/restart', json={}, headers={'Idempotency-Key': 'restart'}).status_code == 403


def test_grant_edits_apply_to_both_rotation_credentials(owner):
    first = issue(owner)
    rotated = owner[0].post('/api/v1/tokens/' + first['token']['id'] + '/rotate', json={'expected_revision': 1, 'overlap_seconds': 3600, 'current_password': PASSWORD}).json()
    changed = owner[0].patch('/api/v1/tokens/' + first['token']['id'], json={'expected_revision': 2, 'current_password': PASSWORD, 'grants': [grant('service:read', 'path', 'default')]})
    assert changed.status_code == 200, changed.text
    for secret in [first['secret'], rotated['secret']]:
        assert bearer(secret).get('/api/v1/health').status_code == 403
        assert bearer(secret).get('/api/v1/service/status').status_code == 200


def test_foreign_instance_and_expiry_policy(owner):
    token = issue(owner)
    with Session(get_engine()) as session:
        row = session.get(ApiToken, token['token']['id']); row.instance_id = 'foreign'; session.add(row); session.commit()
    assert bearer(token['secret']).get('/api/v1/').status_code == 401
    base = {'name': 'T', 'integration': 'I', 'owner_id': owner[1], 'current_password': PASSWORD, 'grants': [grant('health:read', 'path', 'default')]}
    for expiry in [(utcnow() - timedelta(days=1)).isoformat(), (utcnow() + timedelta(days=366)).isoformat(), '2027-01-01T00:00:00']:
        assert owner[0].post('/api/v1/tokens', json={**base, 'expires_at': expiry}).status_code == 422


def test_bulk_revoke_is_atomic_and_unknown_ids_cannot_partially_revoke(owner):
    one, two = issue(owner), issue(owner)
    fail = owner[0].post('/api/v1/tokens/revoke', json={'ids': [one['token']['id'], 'unknown']})
    assert fail.status_code == 404
    assert bearer(one['secret']).get('/api/v1/').status_code == 200
    ok = owner[0].post('/api/v1/tokens/revoke', json={'ids': [one['token']['id'], two['token']['id']]})
    assert ok.status_code == 200
    assert bearer(one['secret']).get('/api/v1/').status_code == 401
    assert bearer(two['secret']).get('/api/v1/').status_code == 401


def test_rate_limit_and_stop_capacity_are_separate(owner, monkeypatch):
    from app.core.settings import settings
    from app.services import service_control
    token = issue(owner, [grant('health:read', 'path', 'default'), grant('service:stop', 'path', 'default')])
    monkeypatch.setattr(settings, 'api_requests_per_minute', 1)
    monkeypatch.setattr(service_control, 'perform_service_action', lambda *a, **kw: None)
    client = bearer(token['secret'])
    assert client.get('/api/v1/health').status_code == 200
    limit = client.get('/api/v1/health')
    assert limit.status_code == 429 and limit.headers['retry-after']
    assert client.post('/api/v1/service/stop', json={}, headers={'Idempotency-Key': 'stop'}).status_code == 200


def test_library_crud_has_independent_actions_and_digest_preconditions(owner):
    token = issue(owner, [grant('inputs:read', 'input'), grant('inputs:create', 'input'), grant('inputs:update', 'input'), grant('secrets:update', 'input')])
    client = bearer(token['secret'])
    new = client.post('/api/v1/inputs', json={'value': {'name': 'Remote', 'url': 'https://source.example/live'}})
    assert new.status_code == 200, new.text
    path = '/api/v1/inputs/' + new.json()['id']
    read = client.get(path).json()
    assert client.patch(path, json={'expected_digest': 'wrong', 'value': read['value']}).status_code == 409
    assert client.patch(path, json={'expected_digest': read['digest'], 'value': {**read['value'], 'name': 'Updated'}}).status_code == 200
    assert client.delete(path, params={'expected_digest': read['digest']}).status_code == 404


def test_export_filters_resources_and_keeps_portable_document_valid(owner):
    a = saved(owner, 'A', 'https://secret:password@source.example/live?token=hidden')
    saved(owner, 'B')
    identity = owner[0].get('/api/v1/token-catalogue').json()['instance_id']
    token = issue(owner, [grant('config:export', 'instance', identity), grant('presets:read', 'preset', a['id'])])
    response = bearer(token['secret']).get('/api/v1/config/export')
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['secrets_redacted'] is True
    assert 'hidden' not in response.text and 'password' not in response.text
    assert [p['name'] for p in result['document']['presets']] == ['A']
    from app.services.config_transfer import normalize
    assert len(normalize(result['document'])[0]) == 1


def test_import_preview_is_bound_to_token_and_redacted_replacement_preserves_secret(owner):
    preset = saved(owner, 'A', 'https://secret:password@source.example/live?token=hidden')
    one, two = issue(owner, preset='configuration-transfer'), issue(owner, preset='configuration-transfer')
    one_client, two_client = bearer(one['secret']), bearer(two['secret'])
    doc = one_client.get('/api/v1/config/export').json()['document']
    decisions = [{'key': 'preset:0', 'action': 'replace'}]
    body = {'document': doc, 'decisions': decisions}
    preview = one_client.post('/api/v1/config/import/preview', json=body)
    assert preview.status_code == 200, preview.text
    body['preview_token'] = preview.json()['preview_token']
    assert two_client.post('/api/v1/config/import', json=body).status_code == 409
    commit = one_client.post('/api/v1/config/import', json=body)
    assert commit.status_code == 200, commit.text
    url = owner[0].get('/api/config/saved/' + preset['id']).json()['bundle']['site']['input']['url']
    assert 'password' in url and 'hidden' in url


def test_spec_exposes_bearer_and_explicit_scope_metadata(owner):
    token = issue(owner)
    result = bearer(token['secret']).get('/api/v1/openapi.json')
    assert result.status_code == 200, result.text
    spec = result.json()
    assert spec['components']['securitySchemes']['IntegrationToken']['scheme'] == 'bearer'
    assert spec['paths']['/api/v1/service/stop']['post']['x-required-scope'] == 'service:stop'
    assert '/api/auth/users' not in spec['paths'] and '/api/v1/tokens' not in spec['paths']


def test_https_does_not_trust_direct_forwarded_proto_header(owner):
    token = issue(owner)
    response = bearer(token['secret'], secure=False).get('/api/v1/health', headers={'X-Forwarded-Proto': 'https'})
    assert response.status_code == 400


def test_two_simultaneous_rotations_cannot_publish_unexpected_credentials(owner):
    from concurrent.futures import ThreadPoolExecutor
    first = issue(owner)
    cookies = dict(owner[0].cookies)
    csrf = owner[0].headers['X-CSRF-Token']
    def rotate():
        client = TestClient(app, base_url='https://testserver', cookies=cookies, headers={'X-CSRF-Token': csrf})
        return client.post('/api/v1/tokens/' + first['token']['id'] + '/rotate', json={
            'expected_revision': 1, 'overlap_seconds': 0, 'current_password': PASSWORD}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: rotate(), range(2))) == [200, 409]
    with Session(get_engine()) as session:
        assert len(session.exec(select(ApiCredential).where(ApiCredential.token_id == first['token']['id'])).all()) == 2


def test_new_scope_or_resource_errors_fail_closed(owner):
    client, user_id = owner
    base = {'name': 'T', 'integration': 'I', 'owner_id': user_id, 'current_password': PASSWORD,
            'expires_at': (utcnow() + timedelta(days=90)).isoformat()}
    for g in [grant('admin:*', 'instance'), grant('service:restart', 'path', 'other'),
              grant('presets:apply', 'preset', '*', 'other'), grant('health:read', 'preset'),
              grant('presets:read', 'preset', 'missing')]:
        assert client.post('/api/v1/tokens', json={**base, 'grants': [g]}).status_code == 422


def test_explicit_secret_update_and_secret_read_are_independent(owner):
    a = saved(owner, url='https://alice:password@source.example/private-path?token=hidden')
    token = issue(owner, [grant('presets:read', 'preset', a['id']), grant('presets:update', 'preset', a['id']), grant('secrets:update', 'preset', a['id'])])
    client = bearer(token['secret'])
    detail = client.get('/api/v1/presets/' + a['id'])
    assert 'private-path' not in detail.text and 'hidden' not in detail.text
    site = detail.json()['bundle']['site']
    site['input']['url'] = 'https://new-user:new-password@source.example/new-path'
    response = client.patch('/api/v1/presets/' + a['id'], json={'site': site, 'expected_revision': 1})
    assert response.status_code == 200
    assert 'new-password' not in client.get('/api/v1/presets/' + a['id']).text
    site['input']['url'] = 'https://source.example/new-path'
    site['input']['clear_url_secret'] = True
    assert client.patch('/api/v1/presets/' + a['id'], json={'site': site, 'expected_revision': 2}).status_code == 200
    assert owner[0].get('/api/config/saved/' + a['id']).json()['bundle']['site']['input']['url'] == 'https://source.example/new-path'


def test_body_limit_database_permissions_and_migration_idempotence(owner):
    from app.core.db import init_db
    from app.core.settings import settings
    token = issue(owner)
    before = owner[0].get('/api/v1/token-catalogue').json()['instance_id']
    init_db()
    assert owner[0].get('/api/v1/token-catalogue').json()['instance_id'] == before
    assert settings.sqlite_path.stat().st_mode & 0o777 == 0o600
    too_large = bearer(token['secret']).post('/api/v1/config/validate', content=b'X' * 1_048_577)
    assert too_large.status_code == 413


def test_service_reader_can_obtain_exact_selection_without_config_access(owner):
    a = saved(owner)
    detail = owner[0].get('/api/config/saved/' + a['id']).json()
    body = {k: detail[k] for k in ('expected_selection_id', 'app_digest', 'runtime_digest', 'runtime_version')}
    body.update(expected_revision=1, target='default', request_id='selected')
    selected = owner[0].post('/api/config/saved/' + a['id'] + '/apply', json=body).json()['selected']['id']
    token = issue(owner, [grant('service:read', 'path', 'default')])
    client = bearer(token['secret'])
    assert client.get('/api/v1/service/status').json()['selected_id'] == selected
    assert client.get('/api/v1/config').status_code == 403


def test_query_credentials_are_rejected_and_access_log_filter_removes_them(owner):
    import logging
    from app.services.api_boundary import ApiAccessLogFilter
    token = issue(owner)
    response = bearer(token['secret']).get('/api/v1/health', params={'access_token': token['secret']})
    assert response.status_code == 400 and token['secret'] not in response.text
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s %s %s %s %s',
        ('client', 'GET', '/api/v1/health?access_token=' + token['secret'], '1.1', 400), None)
    ApiAccessLogFilter().filter(record)
    assert token['secret'] not in record.getMessage()
