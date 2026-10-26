"""A public client cannot turn a plaintext request into an HTTPS API request."""
from contextlib import contextmanager
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('frontend_proxy', Path(__file__).with_name('serve-frontend.py'))
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class ProxyTests(unittest.TestCase):
    def test_only_configured_proxy_peers_are_trusted(self):
        self.assertTrue(proxy.trusted_proxy('127.0.0.1'))
        self.assertFalse(proxy.trusted_proxy('198.51.100.1'))
        self.assertFalse(proxy.trusted_proxy('invalid'))

    def request(self, peer):
        handler = object.__new__(proxy.SpaRequestHandler)
        handler.path, handler.command = '/api/v1/health', 'GET'
        handler.client_address = (peer, 1234)
        handler.headers = {'Host': 'easysrt.example', 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': 'spoofed', 'Authorization': 'Bearer ephemeral-test'}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *a: None
        handler.send_header = lambda *a: None
        handler.end_headers = lambda: None
        seen = []
        @contextmanager
        def upstream(request, **kwargs):
            seen.append(dict(request.header_items()))
            class Response:
                status = 200
                def getheaders(self): return []
                def read(self): return b'{}'
            yield Response()
        with patch.object(proxy.urllib.request, 'urlopen', upstream):
            handler._proxy_request()
        return {key.lower(): value for key, value in seen[0].items()}

    def test_plaintext_external_headers_cannot_spoof_tls_or_source(self):
        headers = self.request('198.51.100.1')
        self.assertEqual(headers['x-forwarded-proto'], 'http')
        self.assertEqual(headers['x-forwarded-for'], '198.51.100.1')
        self.assertEqual(headers['authorization'], 'Bearer ephemeral-test')

    def test_trusted_ingress_preserves_tls_and_bearer_header(self):
        headers = self.request('127.0.0.1')
        self.assertEqual(headers['x-forwarded-proto'], 'https')
        self.assertEqual(headers['authorization'], 'Bearer ephemeral-test')
