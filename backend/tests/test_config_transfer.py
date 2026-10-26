from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.core.db import get_engine
from app.core.settings import settings
from app.main import app
from app.models.site_config import SavedInputRecord, SavedSiteConfigRecord, SiteConfigState
from app.services import config_transfer as transfer
from app.services.config_service import load_bundle, save_bundle, build_runtime_config
from app.schemas.config import SiteConfig


@pytest.fixture
def client():
    with TestClient(app) as c:
        r = c.post('/api/auth/bootstrap-owner', json={'username': 'owner', 'password': 'test-secure-password', 'role': 'owner'})
        assert r.status_code == 200
        c.headers['X-CSRF-Token'] = r.json()['csrf_token']
        bundle = load_bundle()
        save_bundle(bundle.app, bundle.site)
        yield c


@pytest.fixture
def legacy():
    return json.loads((Path(__file__).parent / 'fixtures/april-extraction.json').read_text())


def preview(client, document, decisions=None):
    return client.post('/api/config/transfer/preview', json={'document': document, 'decisions': decisions or []})


def apply(client, document, decisions, token):
    return client.post('/api/config/transfer/import', json={'document': document, 'decisions': decisions, 'preview_token': token})


def reviewed(client, document):
    r = preview(client, document)
    assert r.status_code == 200, r.text
    decisions = [{'key': i['key'], 'action': 'add', **({'latency_ms': 120} if i['requires_latency_review'] else {})} for i in r.json()['items']]
    result = preview(client, document, decisions)
    assert result.status_code == 200, result.text
    assert result.json()['can_import'], result.text
    return decisions, result.json()['preview_token']


def fingerprint():
    c = sqlite3.connect(settings.sqlite_path)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    rows = {t: c.execute('SELECT * FROM "' + t + '" ORDER BY rowid').fetchall() for t in tables}
    c.close()
    files = {p.name: p.read_bytes() for p in settings.data_dir.iterdir() if p.suffix != '.db'}
    return rows, files


def test_april_preview_is_read_only_redacted_and_requires_review(client, legacy):
    legacy['saved_inputs'][0]['input_payload']['url'] = 'https://user:secret@audio.example.test/live?access_token=private#secret'
    legacy['saved_inputs'][0]['input_payload']['name'] = 'https://user:secret@audio.example.test/live?access_token=private'
    before = fingerprint()
    r = preview(client, legacy)
    assert r.status_code == 200
    assert len(r.json()['items']) == 10
    assert not r.json()['can_import']
    assert len(r.json()['errors']) == 6
    assert 'user:secret' not in r.text and 'private' not in r.text
    assert 'DO NOT EXECUTE' not in r.text
    assert fingerprint() == before


def test_unreviewed_legacy_latency_cannot_be_committed(client, legacy):
    p = preview(client, legacy).json()
    before = fingerprint()
    assert apply(client, legacy, [], p['preview_token']).status_code == 422
    assert fingerprint() == before


def test_review_preserves_original_latency_label(client, legacy):
    original = legacy['saved_configs'][0]['site_payload']['profile']['srt_latency_ms']
    p = preview(client, legacy, [{'key': 'preset:0', 'action': 'add', 'latency_ms': original + 1}]).json()
    assert p['items'][0]['source_latency_ms'] == original
    assert p['items'][0]['latency_ms'] == original + 1


@pytest.mark.parametrize('payload', [
    '{"name":"secret-name","name":"other","url":"https://example.test/live"}',
    '{"name":"secret-name","url":"https://example.test/live","extra":NaN}',
])
def test_embedded_legacy_json_uses_strict_parser(client, legacy, payload):
    legacy['saved_inputs'][0]['input_payload'] = payload
    before = fingerprint()
    r = preview(client, legacy)
    assert r.status_code == 422
    assert 'secret-name' not in r.text
    assert fingerprint() == before


@pytest.mark.parametrize('operation', ['preview', 'import'])
def test_blocking_transfer_does_not_block_health(client, legacy, monkeypatch, operation):
    entered, release = threading.Event(), threading.Event()
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return {}
    monkeypatch.setattr(transfer, 'preview' if operation == 'preview' else 'commit_import', blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(client.post, '/api/config/transfer/' + operation, json={'document': legacy})
        try:
            assert entered.wait(3)
            health = pool.submit(client.get, '/health')
            assert health.result(timeout=1).status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=3).status_code == 200


def test_engineer_can_review_and_import_without_owner_access(client, legacy):
    client.post('/api/auth/users', json={'username': 'engineer', 'password': 'engineer-password-test', 'role': 'engineer'})
    r = client.post('/api/auth/login', json={'username': 'engineer', 'password': 'engineer-password-test'})
    client.headers['X-CSRF-Token'] = r.json()['csrf_token']
    decisions, token = reviewed(client, legacy)
    assert apply(client, legacy, decisions, token).status_code == 200


def test_item_limit_rejects_whole_import(client):
    d = client.get('/api/config/transfer/export').json()
    d['inputs'] = [{'name': str(i), 'url': 'https://audio.example.test/live'} for i in range(501)]
    before = fingerprint()
    assert preview(client, d).status_code == 422
    assert fingerprint() == before


def test_import_all_preserves_active_files_accounts_and_replication(client, legacy, monkeypatch):
    from app.services import host_control
    monkeypatch.setattr(host_control, 'request_helper', lambda *a, **k: pytest.fail('Import touched helper'))
    before_rows, before_files = fingerprint()
    decisions, token = reviewed(client, legacy)
    r = apply(client, legacy, decisions, token)
    assert r.status_code == 200, r.text
    assert len(r.json()['imported']) == 10
    assert r.json()['active_configuration_changed'] is False
    rows, files = fingerprint()
    assert files == before_files
    for table in before_rows:
        if table not in {'savedsiteconfigrecord', 'savedinputrecord', 'saveddestinationrecord'}:
            assert rows[table] == before_rows[table]
    assert len(rows['savedsiteconfigrecord']) == 6
    assert len(rows['savedinputrecord']) == 1
    assert len(rows['saveddestinationrecord']) == 3
    with Session(get_engine()) as s:
        presets = s.exec(select(SavedSiteConfigRecord)).all()
        for p in presets:
            assert not p.id.startswith('old-')
            site = SiteConfig.model_validate_json(p.site_payload)
            cmd = build_runtime_config(load_bundle().app, site).ffmpeg_command
            assert 'latency=120000' in cmd
            if site.profile.enable_video:
                assert cmd.index('color=c=black') < cmd.index('-c:a')


def test_export_round_trip_and_no_identity_or_runtime_secrets(client, legacy):
    decisions, token = reviewed(client, legacy)
    assert apply(client, legacy, decisions, token).status_code == 200
    r = client.get('/api/config/transfer/export')
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-store'
    d = r.json()
    assert d['format'] == transfer.FORMAT and d['schema_version'] == 1
    assert len(d['presets']) == 6 and len(d['inputs']) == 1 and len(d['destinations']) == 3
    assert 'ffmpeg_command' not in r.text and 'password_hash' not in r.text and 'created_by_user_id' not in r.text
    rows, legacy_flag, _ = transfer.normalize(d)
    assert not legacy_flag
    assert len(rows) == 11  # Includes a separate snapshot of the current configuration.
    r = preview(client, d)
    assert not r.json()['errors']
    assert all(i['action'] == 'skip' for i in r.json()['items'])
    # Rename the current snapshot; all other entries stay skipped by default.
    decision = [{'key': 'current', 'action': 'add', 'name': 'Recovered snapshot'}]
    p = preview(client, d, decision).json()
    assert p['can_import']
    assert len(apply(client, d, decision, p['preview_token']).json()['imported']) == 1


@pytest.mark.parametrize('change', ['future', 'unknown', 'profile-extra', 'bad-rate', 'missing-profile-field', 'legacy-flat', 'users', 'duplicate-decisions', 'embedded-destination-options'])
def test_invalid_imports_have_no_effect(client, legacy, change):
    d = client.get('/api/config/transfer/export').json()
    decisions = []
    if change == 'future': d['schema_version'] = 99
    elif change == 'unknown': d['future_setting'] = True
    elif change == 'profile-extra': d['current']['site']['profile']['extra_codec'] = 'unknown'
    elif change == 'bad-rate': d['current']['site']['profile']['sample_rate_hz'] = 12345
    elif change == 'missing-profile-field': del d['current']['site']['profile']['pcr_period_ms']
    elif change == 'legacy-flat': d = {'input_source': 'mbstudio', 'mpegts_audio_pid': 2101}
    elif change == 'users': d['users'] = [{'password': 'do-not-echo'}]
    elif change == 'embedded-destination-options': d['current']['site']['destination']['host'] = 'srt://receiver.example.test:16000?passphrase=do-not-echo'
    elif change == 'duplicate-decisions': decisions = [{'key': 'current', 'action': 'skip'}] * 2
    before = fingerprint()
    r = preview(client, d, decisions)
    assert r.status_code == 422
    assert 'do-not-echo' not in r.text
    assert fingerprint() == before


def test_bare_site_and_old_bundle_are_supported_without_executing_runtime(client, legacy):
    for d in [legacy['active_site'], {'app': legacy['app'], 'site': legacy['active_site'], 'runtime': {'ffmpeg_command': 'touch /tmp/NEVER'}}]:
        p = preview(client, d)
        assert p.status_code == 200
        assert p.json()['items'][0]['requires_latency_review']
        assert not p.json()['can_import']
        assert 'touch' not in p.text


@pytest.mark.parametrize('mutation', ['document', 'decision', 'database', 'runtime', 'expired', 'replay'])
def test_stale_modified_or_replayed_previews_rejected(client, legacy, mutation, monkeypatch):
    decisions, token = reviewed(client, legacy)
    if mutation == 'document': legacy['saved_configs'][0]['site_payload']['profile']['mux_rate_kbps'] = 1500
    elif mutation == 'decision': decisions[0]['name'] = 'Changed after review'
    elif mutation == 'database':
        with Session(get_engine()) as s:
            s.add(SavedInputRecord(name='Concurrent edit', input_payload=json.dumps(legacy['saved_inputs'][0]['input_payload'])))
            s.commit()
    elif mutation == 'runtime': settings.sender_env_path.write_text('changed after preview')
    elif mutation == 'expired': monkeypatch.setattr(transfer, 'PREVIEW_TTL', -1)
    elif mutation == 'replay': assert apply(client, legacy, decisions, token).status_code == 200
    before = fingerprint()
    r = apply(client, legacy, decisions, token)
    assert r.status_code == 409, r.text
    assert fingerprint() == before


def test_conflicts_skip_rename_replace_and_library_revision(client, legacy):
    decisions, token = reviewed(client, legacy)
    assert apply(client, legacy, decisions, token).status_code == 200
    p = preview(client, legacy).json()
    assert all(i['action'] == 'skip' for i in p['items'])
    assert not p['can_import']
    decision = [{'key': 'preset:0', 'action': 'add', 'name': 'Renamed import', 'latency_ms': 80}]
    p = preview(client, legacy, decision).json()
    assert p['can_import']
    assert len(apply(client, legacy, decision, p['preview_token']).json()['imported']) == 1
    decision = [{'key': 'preset:0', 'action': 'replace', 'latency_ms': 250}]
    p = preview(client, legacy, decision).json()
    assert apply(client, legacy, decision, p['preview_token']).status_code == 200
    with Session(get_engine()) as s:
        target = s.exec(select(SavedSiteConfigRecord).where(SavedSiteConfigRecord.name == 'Example preset 1')).one()
        assert json.loads(target.site_payload)['profile']['srt_latency_ms'] == 250
        target_id = target.id
        s.add(SiteConfigState(active_saved_config_id=target_id)); s.commit()
    p = preview(client, legacy, decision).json()
    assert p['can_import']
    assert apply(client, legacy, decision, p['preview_token']).status_code == 200
    with Session(get_engine()) as s:
        assert s.get(SavedSiteConfigRecord, target_id).revision == 3


def test_duplicate_target_names_block_the_entire_plan(client, legacy):
    decisions, _ = reviewed(client, legacy)
    decisions[0]['name'] = decisions[1]['name'] = 'Same target'
    p = preview(client, legacy, decisions).json()
    assert not p['can_import'] and any('duplicate target' in e for e in p['errors'])


def test_database_failure_rolls_back_all_entries(client, legacy, monkeypatch):
    decisions, token = reviewed(client, legacy)
    before = fingerprint()
    original = Session.add
    def failing_add(s, record, *args, **kwargs):
        if isinstance(record, SavedInputRecord): raise RuntimeError('injected storage failure')
        return original(s, record, *args, **kwargs)
    monkeypatch.setattr(Session, 'add', failing_add)
    with pytest.raises(RuntimeError, match='injected storage failure'):
        apply(client, legacy, decisions, token)
    assert fingerprint() == before


def test_preview_token_is_scoped_to_user_and_writes_require_csrf(client, legacy):
    decisions, token = reviewed(client, legacy)
    assert client.post('/api/auth/users', json={'username': 'other', 'password': 'other-password-test', 'role': 'engineer'}).status_code == 200
    r = client.post('/api/auth/login', json={'username': 'other', 'password': 'other-password-test'})
    client.headers['X-CSRF-Token'] = r.json()['csrf_token']
    assert apply(client, legacy, decisions, token).status_code == 409
    client.headers.pop('X-CSRF-Token')
    assert preview(client, legacy).status_code == 403


def test_operator_and_unauthenticated_requests_denied(client, legacy):
    client.post('/api/auth/users', json={'username': 'operator', 'password': 'operator-password-test', 'role': 'operator'})
    r = client.post('/api/auth/login', json={'username': 'operator', 'password': 'operator-password-test'})
    client.headers['X-CSRF-Token'] = r.json()['csrf_token']
    assert preview(client, legacy).status_code == 403
    assert client.get('/api/config/transfer/export').status_code == 403
    client.cookies.clear()
    assert preview(client, legacy).status_code == 401
    assert client.get('/api/config/transfer/export').status_code == 401


def test_size_limits_invalid_json_and_sanitized_errors(client):
    r = client.post('/api/config/transfer/preview', content=b'x' * (transfer.MAX_BYTES + 1))
    assert r.status_code == 413
    for raw in ['{broken secret-password', '{"document": "secret-password"}', '{"document": {"schema_version": NaN}}', '{"document":{},"document":{}}']:
        r = client.post('/api/config/transfer/preview', content=raw)
        assert r.status_code == 422 and 'secret-password' not in r.text


def test_local_activation_waits_for_import_writer_lock_before_runtime_writes(client, legacy, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from app.services import config_snapshots
    from test_presets import save as save_preset, review, apply_body
    preset = save_preset(client)
    body = apply_body(review(client, preset))
    waiting, wrote_files = threading.Event(), threading.Event()
    original = config_snapshots.stage
    def save(*args):
        wrote_files.set()
        return original(*args)
    monkeypatch.setattr(config_snapshots, 'stage', save)
    decisions, token = reviewed(client, legacy)
    main_thread = threading.get_ident()
    def before_execute(conn, cursor, statement, params, context, executemany):
        if statement == 'BEGIN IMMEDIATE' and threading.get_ident() != main_thread:
            waiting.set()
    site = load_bundle().site.model_dump()
    site['profile']['mux_rate_kbps'] = 1500
    event.listen(Engine, 'before_cursor_execute', before_execute)
    try:
        with Session(get_engine()) as holder, ThreadPoolExecutor(max_workers=1) as pool:
            holder.connection().exec_driver_sql('BEGIN IMMEDIATE')
            future = pool.submit(client.post, f"/api/config/saved/{preset['id']}/apply", json=body)
            try:
                assert waiting.wait(3)
                assert not wrote_files.wait(0.1)
            finally:
                holder.rollback()
            assert future.result(timeout=5).status_code == 200
            assert wrote_files.is_set()
    finally:
        event.remove(Engine, 'before_cursor_execute', before_execute)
    assert apply(client, legacy, decisions, token).status_code == 409
