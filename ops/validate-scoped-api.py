#!/usr/bin/env python3
"""Disposable localhost TLS API rehearsal; never points at an installed sender."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    cases = []
    with tempfile.TemporaryDirectory(prefix='easysrt-api-tls-') as raw:
        folder = Path(raw)
        cert, key = folder / 'cert.pem', folder / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost',
            '-keyout', str(key), '-out', str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        data = folder / 'data'; data.mkdir(mode=0o700)
        env = {**os.environ, 'EASYSRT_ENVIRONMENT': 'production', 'EASYSRT_SECRET_KEY': secrets.token_hex(32),
               'EASYSRT_TRUSTED_HOSTS': '127.0.0.1,localhost', 'EASYSRT_FRONTEND_ORIGIN': f'https://127.0.0.1:{port}', 'EASYSRT_SESSION_COOKIE_SECURE': 'true',
               'EASYSRT_HELPER_SOCKET_PATH': str(folder / 'no-host-control.sock'), 'EASYSRT_DATA_DIR': str(data),
               'EASYSRT_SQLITE_PATH': str(data / 'easysrt.db')}
        for name, filename in [('APP_CONFIG_PATH', 'app_config.json'), ('SITE_CONFIG_PATH', 'site_config.json'),
                ('RUNTIME_CONFIG_PATH', 'runtime_config.json'), ('SENDER_ENV_PATH', 'sender.env')]:
            env['EASYSRT_' + name] = str(data / filename)
        log = open(folder / 'server.log', 'w+')
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
            '--port', str(port), '--ssl-keyfile', str(key), '--ssl-certfile', str(cert), '--no-proxy-headers'],
            cwd=ROOT / 'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            # A fixture-specific trust root; verification is never disabled and no
            # certificate is installed in the user's/system/browser trust store.
            context = ssl.create_default_context(cafile=str(cert))
            base = f'https://127.0.0.1:{port}'
            with httpx.Client(base_url=base, verify=context, timeout=10) as owner:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        if owner.get('/health').status_code == 200: break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError('Disposable TLS API did not start')
                    time.sleep(.1)
                password = secrets.token_urlsafe(24)
                response = owner.post('/api/auth/bootstrap-owner', json={'username': 'fixture', 'password': password, 'role': 'owner'})
                assert response.status_code == 200
                owner_id = response.json()['user']['id']
                owner.headers['X-CSRF-Token'] = response.json()['csrf_token']
                catalogue = owner.get('/api/v1/token-catalogue').json()
                grants = next(p['grants'] for p in catalogue['presets'] if p['id'] == 'monitor')
                created = owner.post('/api/v1/tokens', json={'name': 'TLS fixture', 'integration': 'disposable', 'owner_id': owner_id,
                    'current_password': password, 'preset': 'monitor', 'grants': grants,
                    'expires_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
                assert created.status_code == 201
                token = created.json()
                cases.append({'case': 'verified_tls_and_owner_session_csrf_issuance', 'passed': True})
                with httpx.Client(base_url=base, verify=context, headers={'Authorization': 'Bearer ' + token['secret']}, timeout=10) as api:
                    health = api.get('/api/v1/health')
                    assert health.status_code == 200 and health.json()['media']['state'] == 'unknown'
                    assert health.headers['cache-control'] == 'no-store'
                    assert api.get('/api/v1/metrics').status_code == 200
                    assert api.get('/api/config').status_code == 401
                    assert api.post('/api/v1/service/stop', json={}, headers={'Idempotency-Key': 'stop'}).status_code == 403
                    assert api.get('/api/v1/openapi.json').status_code == 200
                    assert api.get('/api/v1/health', params={'access_token': token['secret']}).status_code == 400
                    cases.append({'case': 'bearer_health_metrics_spec_and_scope_legacy_denials', 'passed': True})
                    metadata = owner.get('/api/v1/tokens').text
                    assert token['secret'] not in metadata
                    with sqlite3.connect(data / 'easysrt.db') as database:
                        dump = '\n'.join(database.iterdump())
                    assert token['secret'] not in dump and password not in dump
                    cases.append({'case': 'one_time_secret_absent_from_metadata_database_and_audit', 'passed': True})
                    rotated = owner.post('/api/v1/tokens/' + token['token']['id'] + '/rotate', json={
                        'expected_revision': 1, 'overlap_seconds': 0, 'current_password': password})
                    assert rotated.status_code == 200
                    assert api.get('/api/v1/health').status_code == 401
                    api.headers['Authorization'] = 'Bearer ' + rotated.json()['secret']
                    assert api.get('/api/v1/health').status_code == 200
                    assert owner.post('/api/v1/tokens/' + token['token']['id'] + '/revoke').status_code == 200
                    assert api.get('/api/v1/health').status_code == 401
                    cases.append({'case': 'rotation_and_revocation_take_effect_over_live_tls', 'passed': True})
                log.flush(); log.seek(0); contents = log.read()
                assert password not in contents and token['secret'] not in contents and rotated.json()['secret'] not in contents
                cases.append({'case': 'credentials_absent_from_access_logs', 'passed': True})
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            log.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({'environment': 'isolated localhost TLS uvicorn; production security settings; no host helper',
        'tls_verification': 'fixture CA trusted explicitly, verification enabled; no system trust changes', 'cases': cases}, indent=2) + '\n')
    print(f'{len(cases)} TLS lifecycle cases passed; disposable server and credentials removed')


if __name__ == '__main__':
    main()
