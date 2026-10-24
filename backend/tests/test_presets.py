"""Preset library, selection publication and sender boundary regressions."""
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.main import app
from app.core.db import get_engine
from app.core.settings import settings
from app.models.site_config import ConfigSnapshot, SelectedConfigState
from app.models.redundancy import ReplicatedConfigState
from app.services import config_snapshots as snapshots, service_control
from app.services.authorization import Principal, Grant, require_principal
from app.services.config_service import load_bundle


@pytest.fixture
def client():
    with TestClient(app) as client:
        login = client.post('/api/auth/bootstrap-owner', json={'username': 'owner', 'password': 'supersecurepass', 'role': 'owner'})
        assert login.status_code == 200
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        yield client
    app.dependency_overrides.clear()


def save(client, name='A', host='receiver-a.example'):
    site = load_bundle().site.model_dump()
    site['destination']['host'] = host
    response = client.post('/api/config/saved', json={'name': name, 'site': site})
    assert response.status_code == 200, response.text
    return response.json()['saved_config']


def review(client, preset):
    response = client.get(f"/api/config/saved/{preset['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def apply_body(detail):
    return {key: detail[key] for key in ('app_digest', 'runtime_digest', 'runtime_version', 'expected_selection_id')} | {
        'expected_revision': detail['saved_config']['revision'], 'request_id': str(uuid4()), 'target': 'default'}


def apply(client, preset, detail=None):
    response = client.post(f"/api/config/saved/{preset['id']}/apply", json=apply_body(detail or review(client, preset)))
    assert response.status_code == 200, response.text
    return response.json()


def files():
    return {str(p.relative_to(settings.data_dir)): p.read_bytes() for p in settings.data_dir.rglob('*')
            if p.is_file() and p.suffix != '.db' and 'easysrt.db' not in p.name}


def test_save_open_overwrite_rename_delete_do_not_publish(client):
    a = save(client)
    assert 'bundle' not in client.post('/api/config/saved', json={'name': 'B', 'site': load_bundle().site.model_dump()}).json()
    selected = apply(client, a)
    before = files()
    detail = review(client, a)
    site = detail['bundle']['site']
    site['destination']['host'] = 'tomorrow.example'
    updated = client.put(f"/api/config/saved/{a['id']}", json={'site': site, 'expected_revision': 1})
    assert updated.json()['saved_config']['revision'] == 2
    assert client.patch(f"/api/config/saved/{a['id']}", json={'name': 'Tomorrow', 'expected_revision': 2}).status_code == 200
    assert client.delete(f"/api/config/saved/{a['id']}?expected_revision=3").status_code == 200
    assert client.get('/api/config').json()['selected'] == selected['selected']
    assert files() == before
    with Session(get_engine()) as session:
        assert session.get(ReplicatedConfigState, 'default').current_version == 2
    assert load_bundle().site.destination.host == 'receiver-a.example'


def test_apply_publishes_once_and_does_not_call_service(client, monkeypatch):
    monkeypatch.setattr(service_control, 'request_helper', lambda *a, **k: pytest.fail('Apply must not control service'))
    a = save(client)
    body = apply_body(review(client, a))
    first = client.post(f"/api/config/saved/{a['id']}/apply", json=body)
    assert first.status_code == 200, first.text
    repeated = client.post(f"/api/config/saved/{a['id']}/apply", json=body)
    assert repeated.json() == first.json()
    with Session(get_engine()) as session:
        assert len(session.exec(select(ConfigSnapshot)).all()) == 1
        assert session.get(ReplicatedConfigState, 'default').current_version == 2
    runtime = json.loads((settings.data_dir / 'selected/runtime_config.json').read_text())
    assert runtime['snapshot_id'] == first.json()['selected']['id']
    assert not settings.sender_env_path.exists()


def test_stale_revision_selection_and_effective_settings_conflict(client):
    a = save(client)
    old = review(client, a)
    assert client.put(f"/api/config/saved/{a['id']}", json={'site': old['bundle']['site'], 'expected_revision': 1}).status_code == 200
    assert client.post(f"/api/config/saved/{a['id']}/apply", json=apply_body(old)).status_code == 409
    fresh = review(client, a)
    assert client.put('/api/config/app', json={'station_name': 'New station', 'support_contact': 's@example.com'}).status_code == 200
    assert client.post(f"/api/config/saved/{a['id']}/apply", json=apply_body(fresh)).status_code == 409
    a_detail = review(client, a)
    b = save(client, 'B')
    apply(client, b)
    assert client.post(f"/api/config/saved/{a['id']}/apply", json=apply_body(a_detail)).status_code == 409
    assert client.delete(f"/api/config/saved/{a['id']}").status_code == 428
    assert client.post(f"/api/config/saved/{a['id']}/load").status_code == 410
    assert client.put('/api/config/site', json=old['bundle']['site']).status_code == 410


def test_publication_failure_restores_pointer_and_database(client, monkeypatch):
    a = save(client)
    first = apply(client, a)
    b = save(client, 'B', 'receiver-b.example')
    body = apply_body(review(client, b))
    original = snapshots.switch_pointer
    def switch_then_fail(identity):
        original(identity)
        if identity != first['selected']['id']:
            raise OSError('injected power loss after rename')
    monkeypatch.setattr(snapshots, 'switch_pointer', switch_then_fail)
    with pytest.raises(OSError):
        client.post(f"/api/config/saved/{b['id']}/apply", json=body)
    assert load_bundle().selected.id == first['selected']['id']
    with Session(get_engine()) as session:
        assert session.get(SelectedConfigState, 'default').snapshot_id == first['selected']['id']
        assert session.get(ReplicatedConfigState, 'default').current_version == 2


def test_edit_only_and_apply_only_principals_are_separate(client):
    from app.models.auth import User
    a = save(client)
    detail = review(client, a)
    body = apply_body(detail)
    with Session(get_engine()) as session:
        user = session.exec(select(User)).first()
    app.dependency_overrides[require_principal] = lambda: Principal(user, (Grant('presets:update', a['id']),))
    assert client.post(f"/api/config/saved/{a['id']}/apply", json=body).status_code == 403
    assert client.post('/api/config/saved', json={'name': 'A', 'site': detail['bundle']['site'], 'overwrite': True,
                      'target_id': a['id'], 'expected_revision': 1}).status_code == 200
    app.dependency_overrides[require_principal] = lambda: Principal(user, (Grant('presets:apply', a['id'], 'default'),))
    body['expected_revision'] = 2
    assert client.post(f"/api/config/saved/{a['id']}/apply", json=body).status_code == 200
    assert client.post('/api/service/restart', json={}).status_code == 403
    assert client.post('/api/service/start', json={}).status_code == 403
    body['target'] = 'another-instance'
    assert client.post(f"/api/config/saved/{a['id']}/apply", json=body).status_code == 403


def test_start_requires_exact_selection_and_pins_reviewed_generation(client, monkeypatch):
    from app.schemas.system import DiagnosticCheck
    a = save(client)
    selected = apply(client, a)
    state = {'service_state': 'inactive'}
    actions = []
    def helper(action, *, actor, payload=None):
        if action == 'sender_status':
            return state
        actions.append((action, payload))
        return {}
    monkeypatch.setattr(service_control, 'request_helper', helper)
    monkeypatch.setattr(service_control, 'collect_preflight_checks', lambda: [])
    assert client.post('/api/service/start').status_code == 428
    assert client.post('/api/service/start', json={'expected_selection_id': str(uuid4())}).status_code == 409
    assert actions == []
    assert client.post('/api/service/start', json={'expected_selection_id': selected['selected']['id']}).status_code == 200
    assert actions == [('sender_start', {'expected_snapshot_id': selected['selected']['id']})]
    state['service_state'] = 'active'
    monkeypatch.setattr(service_control, 'collect_preflight_checks', lambda: [DiagnosticCheck(name='bad', ok=False, detail='offline', severity='critical', category='input', blocking=True)])
    assert client.post('/api/service/stop').status_code == 200
    assert actions[-1][0] == 'sender_stop'


def test_running_identity_uses_fresh_matching_snapshot_not_selected(client, monkeypatch):
    from app.schemas.system import SenderHealth
    a = apply(client, save(client))
    b = apply(client, save(client, 'B', 'receiver-b.example'))
    monkeypatch.setattr(service_control, 'collect_preflight_checks', lambda: [])
    monkeypatch.setattr(service_control, 'request_helper', lambda *a, **k: {'service_state': 'active'})
    monkeypatch.setattr(service_control, 'read_sender_health', lambda *args: SenderHealth(snapshot_id=a['selected']['id']))
    status = client.get('/api/service/status').json()
    assert status['running_config']['site']['destination']['host'] == 'receiver-a.example'
    assert status['selected']['id'] == b['selected']['id']
    assert status['pending_configuration'] is True
    monkeypatch.setattr(service_control, 'read_sender_health', lambda *args: SenderHealth())
    status = client.get('/api/service/status').json()
    assert status['running_config'] is None and status['pending_configuration'] is None


def test_app_metadata_and_import_overwrite_leave_selected_snapshot_unchanged(client):
    a = save(client)
    selected = apply(client, a)
    before = files()
    assert client.put('/api/config/app', json={'station_name': 'Tomorrow', 'support_contact': 's@example.com'}).status_code == 200
    assert load_bundle().app.station_name == selected['app']['station_name']
    doc = client.get('/api/config/transfer/export').json()
    doc['presets'][0]['site']['destination']['host'] = 'tomorrow.example'
    decisions = [{'key': 'preset:0', 'action': 'replace'}]
    preview = client.post('/api/config/transfer/preview', json={'document': doc, 'decisions': decisions})
    assert preview.status_code == 200, preview.text
    result = client.post('/api/config/transfer/import', json={'document': doc, 'decisions': decisions, 'preview_token': preview.json()['preview_token']})
    assert result.status_code == 200, result.text
    assert result.json()['active_configuration_changed'] is False
    assert load_bundle().selected.id == selected['selected']['id']
    assert review(client, a)['saved_config']['revision'] == 2
    assert {k: v for k, v in files().items() if k.startswith('generations/')} == {k: v for k, v in before.items() if k.startswith('generations/')}


@pytest.mark.parametrize('boundary', ['stage', 'commit'])
def test_failed_generation_or_database_commit_preserves_previous_selection(client, monkeypatch, boundary):
    from sqlalchemy.orm import Session as SASession
    a = apply(client, save(client))
    b = save(client, 'B')
    body = apply_body(review(client, b))
    def fail(*args, **kwargs):
        raise OSError('injected publication failure')
    monkeypatch.setattr(snapshots if boundary == 'stage' else SASession, 'stage' if boundary == 'stage' else 'commit', fail)
    with pytest.raises(OSError):
        client.post(f"/api/config/saved/{b['id']}/apply", json=body)
    assert load_bundle().selected.id == a['selected']['id']
    assert json.loads((settings.data_dir / 'selected/bundle.json').read_text())['runtime']['snapshot_id'] == a['selected']['id']


def _crash_publisher(preset_id, body, user_id):
    import os
    from app.models.auth import User
    from app.schemas.config import ApplyPresetRequest
    original = snapshots.switch_pointer
    def die_after_switch(identity):
        original(identity)
        if identity != body['expected_selection_id']:
            os._exit(71)
    snapshots.switch_pointer = die_after_switch
    with Session(get_engine()) as session:
        user = session.get(User, user_id)
        principal = Principal(user, (Grant('presets:apply'),))
        snapshots.apply_preset(principal, preset_id, ApplyPresetRequest.model_validate(body))


def test_process_death_after_pointer_switch_reconciles_to_committed_snapshot(client):
    import os
    import subprocess
    import sys
    from app.models.auth import User
    a = apply(client, save(client))
    b = save(client, 'B')
    body = apply_body(review(client, b))
    with Session(get_engine()) as session:
        user_id = session.exec(select(User)).first().id
    paths = {name: str(getattr(settings, name).resolve()) for name in (
        'data_dir', 'sqlite_path', 'app_config_path', 'site_config_path', 'runtime_config_path', 'sender_env_path')}
    program = """
import json, sys
from pathlib import Path
from app.core.settings import settings
for name, path in json.loads(sys.argv[1]).items():
    setattr(settings, name, Path(path))
from test_presets import _crash_publisher
_crash_publisher(sys.argv[2], json.loads(sys.argv[3]), sys.argv[4])
"""
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c', program, json.dumps(paths), b['id'], json.dumps(body), user_id],
                            env={**os.environ, 'PYTHONPATH': os.pathsep.join((str(backend), str(backend / 'tests')))},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 71, result.stderr
    # The file pointer changed but SQLite rolled back the uncommitted journal.
    assert (settings.data_dir / 'selected').resolve().name != a['selected']['id']
    assert load_bundle().selected.id == a['selected']['id']
    assert (settings.data_dir / 'selected').resolve().name == a['selected']['id']


def test_simultaneous_apply_requests_conflict_instead_of_silently_replacing_selection(client):
    from concurrent.futures import ThreadPoolExecutor
    a, b = save(client), save(client, 'B')
    requests = [(p, apply_body(review(client, p))) for p in (a, b)]
    def send(item):
        preset, body = item
        return client.post(f"/api/config/saved/{preset['id']}/apply", json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, requests))
    assert sorted(r.status_code for r in results) == [200, 409]
    assert load_bundle().selected.id == next(r.json()['selected']['id'] for r in results if r.status_code == 200)


def test_legacy_migration_is_idempotent_and_never_claims_running_identity(client):
    from app.services.config_service import save_bundle
    save_bundle(load_bundle().app, load_bundle().site)
    snapshots.migrate_selection()
    original = load_bundle()
    snapshots.migrate_selection()
    assert load_bundle().selected.id == original.selected.id
    assert not (settings.data_dir / 'applied_sender.json').exists()


def test_existing_database_gets_revision_column_and_private_backup(client):
    import sqlite3
    from app.core.db import init_db
    a = save(client)
    with sqlite3.connect(settings.sqlite_path) as connection:
        connection.execute('ALTER TABLE savedsiteconfigrecord DROP COLUMN revision')
    init_db()
    assert review(client, a)['saved_config']['revision'] == 1
    backup = settings.sqlite_path.with_suffix('.pre-preset-revisions.db')
    assert backup.exists() and backup.stat().st_mode & 0o777 == 0o600
    original = backup.read_bytes()
    init_db()
    assert backup.read_bytes() == original


def test_stop_survives_malformed_unselected_legacy_configuration(client, monkeypatch):
    settings.site_config_path.write_text('{broken')
    monkeypatch.setattr(service_control, 'request_helper', lambda action, **kw: {'service_state': 'active'} if action == 'sender_status' else {})
    assert client.post('/api/service/stop').status_code == 200


@pytest.mark.parametrize('operation', ['update', 'rename', 'delete'])
def test_stale_library_mutations_conflict_without_changing_selection(client, operation):
    preset = save(client)
    selected = apply(client, preset)
    detail = review(client, preset)
    assert client.patch(f"/api/config/saved/{preset['id']}", json={'name': 'Renamed', 'expected_revision': 1}).status_code == 200
    before = files()
    url = f"/api/config/saved/{preset['id']}"
    if operation == 'update':
        response = client.put(url, json={'site': detail['bundle']['site'], 'expected_revision': 1})
    elif operation == 'rename':
        response = client.patch(url, json={'name': 'Stale', 'expected_revision': 1})
    else:
        response = client.delete(url + '?expected_revision=1')
    assert response.status_code == 409
    assert files() == before and load_bundle().selected.id == selected['selected']['id']


@pytest.mark.parametrize('boundary', ['write', 'fsync'])
def test_partial_generation_failure_never_becomes_selected(client, monkeypatch, boundary):
    selected = apply(client, save(client))
    b = save(client, 'B')
    body = apply_body(review(client, b))
    calls = []
    if boundary == 'write':
        original = snapshots.durable_write
        def write(path, content):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('Disk write failed')
            return original(path, content)
        monkeypatch.setattr(snapshots, 'durable_write', write)
    else:
        def fsync(fd):
            raise OSError('Disk flush failed')
        monkeypatch.setattr(snapshots.os, 'fsync', fsync)
    with pytest.raises(OSError):
        client.post(f"/api/config/saved/{b['id']}/apply", json=body)
    assert load_bundle().selected.id == selected['selected']['id']


def test_review_after_save_cannot_silently_open_a_concurrent_overwrite(client):
    preset = save(client)
    detail = review(client, preset)
    assert client.put(f"/api/config/saved/{preset['id']}", json={'site': detail['bundle']['site'], 'expected_revision': 1}).status_code == 200
    assert client.get(f"/api/config/saved/{preset['id']}?expected_revision=1").status_code == 409
    assert client.get(f"/api/config/saved/{preset['id']}?expected_revision=2").status_code == 200


def test_stop_survives_failed_selected_artifact_repair(client, monkeypatch):
    apply(client, save(client))
    (settings.data_dir / 'selected/runtime_config.json').unlink()
    monkeypatch.setattr(snapshots, 'stage', lambda *args: (_ for _ in ()).throw(OSError('Disk unavailable')))
    commands = []
    def helper(action, **kw):
        commands.append(action)
        return {'service_state': 'active'} if action == 'sender_status' else {}
    monkeypatch.setattr(service_control, 'request_helper', helper)
    response = client.post('/api/service/stop')
    assert response.status_code == 200, response.text
    assert 'sender_stop' in commands
    assert response.json()['preflight_ok'] is False


@pytest.mark.parametrize('edit_during_start', [False, True])
def test_start_apply_and_library_save_share_coherent_revision_boundary(client, monkeypatch, edit_during_start):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    import threading
    a = apply(client, save(client))
    b = save(client, 'B')
    detail = review(client, b)
    body = apply_body(detail)
    dispatched, release = threading.Event(), threading.Event()
    commands = []
    def helper(action, *, actor, payload=None):
        if action == 'sender_status':
            return {'service_state': 'inactive'}
        commands.append((action, payload))
        dispatched.set()
        assert release.wait(5)
        return {}
    monkeypatch.setattr(service_control, 'request_helper', helper)
    monkeypatch.setattr(service_control, 'collect_preflight_checks', lambda: [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(client.post, '/api/service/start', json={'expected_selection_id': a['selected']['id']})
        assert dispatched.wait(3)
        try:
            if edit_during_start:
                saved = client.put(f"/api/config/saved/{b['id']}", json={'site': detail['bundle']['site'], 'expected_revision': 1})
                assert saved.status_code == 200
            applied = pool.submit(client.post, f"/api/config/saved/{b['id']}/apply", json=body)
            with pytest.raises(TimeoutError):
                applied.result(timeout=.1)
            assert (settings.data_dir / 'selected').resolve().name == a['selected']['id']
        finally:
            release.set()
        assert started.result(timeout=5).status_code == 200
        assert applied.result(timeout=5).status_code == (409 if edit_during_start else 200)
    assert commands == [('sender_start', {'expected_snapshot_id': a['selected']['id']})]
    assert (load_bundle().selected.id == a['selected']['id']) is edit_during_start


@pytest.mark.parametrize("artifact", ["runtime_config.json", "sender.env"])
def test_selected_artifact_repair_uses_committed_copy_after_library_edit(client, artifact):
    preset = save(client)
    selected = apply(client, preset)
    detail = review(client, preset)
    detail['bundle']['site']['destination']['host'] = 'unselected.example'
    assert client.put(f"/api/config/saved/{preset['id']}", json={'site': detail['bundle']['site'], 'expected_revision': 1}).status_code == 200
    runtime = settings.data_dir / 'selected/runtime_config.json'
    (settings.data_dir / 'selected' / artifact).unlink()
    assert load_bundle().selected.id == selected['selected']['id']
    assert json.loads(runtime.read_text())['snapshot_id'] == selected['selected']['id']
    assert load_bundle().site.destination.host == 'receiver-a.example'
