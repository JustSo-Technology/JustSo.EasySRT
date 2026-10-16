#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.server
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

DEFAULT_PROXY_TIMEOUT_SECONDS = 20
UPDATE_PROXY_TIMEOUT_SECONDS = 60
MAX_REQUEST_BODY_BYTES = 1024 * 1024
TRUSTED_HOSTS = {
    host.strip().lower()
    for host in os.environ.get("EASYSRT_TRUSTED_HOSTS", "").split(",")
    if host.strip()
}


class SpaRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        super().end_headers()

    def _host_is_allowed(self) -> bool:
        if not TRUSTED_HOSTS or "*" in TRUSTED_HOSTS:
            return True
        try:
            hostname = urllib.parse.urlsplit(f"//{self.headers.get('Host', '')}").hostname
        except ValueError:
            return False
        return bool(hostname and hostname.lower() in TRUSTED_HOSTS)

    def _reject_untrusted_host(self) -> bool:
        if self._host_is_allowed():
            return False
        self.send_error(400, "Invalid host header")
        return True

    def do_GET(self) -> None:
        if self._reject_untrusted_host():
            return
        if self.path.startswith("/api/") or self.path == "/health":
            self._proxy_request()
            return

        requested = self.translate_path(self.path)
        if self.path in {"/", ""} or Path(requested).exists():
            super().do_GET()
            return

        self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        if self._reject_untrusted_host():
            return
        self._proxy_request()

    def do_PUT(self) -> None:
        if self._reject_untrusted_host():
            return
        self._proxy_request()

    def do_PATCH(self) -> None:
        if self._reject_untrusted_host():
            return
        self._proxy_request()

    def do_DELETE(self) -> None:
        if self._reject_untrusted_host():
            return
        self._proxy_request()

    def do_OPTIONS(self) -> None:
        if self._reject_untrusted_host():
            return
        self._proxy_request()

    def do_HEAD(self) -> None:
        if self._reject_untrusted_host():
            return
        if self.path.startswith("/api/") or self.path == "/health":
            self._proxy_request(send_body=False)
            return

        requested = self.translate_path(self.path)
        if self.path in {"/", ""} or Path(requested).exists():
            super().do_HEAD()
            return

        self.path = "/index.html"
        super().do_HEAD()

    def _proxy_request(self, send_body: bool = True) -> None:
        target = f"http://127.0.0.1:8000{self.path}"
        body = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            try:
                body_length = int(content_length)
            except ValueError:
                self.send_error(400, "Invalid Content-Length")
                return
            if body_length < 0 or body_length > MAX_REQUEST_BODY_BYTES:
                self.send_error(413, "Request body too large")
                return
            body = self.rfile.read(body_length)

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "x-forwarded-host", "x-forwarded-proto"}
        }
        forwarded_proto = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip().lower()
        if forwarded_proto not in {"http", "https"}:
            forwarded_proto = "http"
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = forwarded_proto
        request = urllib.request.Request(target, data=body, headers=headers, method=self.command)
        timeout = UPDATE_PROXY_TIMEOUT_SECONDS if self.path.startswith("/api/update/") else DEFAULT_PROXY_TIMEOUT_SECONDS
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in HOP_BY_HOP_HEADERS:
                        self.send_header(key, value)
                self.end_headers()
                if send_body:
                    self.wfile.write(response.read())
        except urllib.error.HTTPError as error:
            self.send_response(error.code)
            for key, value in error.headers.items():
                if key.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            if send_body:
                self.wfile.write(error.read())
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if send_body:
                reason = getattr(error, "reason", None) or str(error)
                self.wfile.write(f"Upstream unavailable: {reason}\n".encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Frontend root does not exist: {root}")

    class ThreadingReusableHTTPServer(http.server.ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    handler = lambda *a, **kw: SpaRequestHandler(*a, directory=str(root), **kw)
    with ThreadingReusableHTTPServer((args.host, args.port), handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
