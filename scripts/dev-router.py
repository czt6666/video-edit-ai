#!/usr/bin/env python3
"""Local dev reverse proxy that mirrors the production Caddyfile.

Single origin on :8080, routing to the three backends and enforcing the same
forward_auth gate as Caddy — so the login -> files -> admin -> chat flow works
locally WITHOUT Docker/TLS/rclone.

Routing (identical intent to caddy/Caddyfile):
    /login, /api/auth/*        -> auth-service        (public)
    <everything else>          -> forward_auth gate against auth-service, then:
        /admin, /admin/*       -> auth-service
        /files, /api/files/*   -> file-manager
        default                -> agent (claudecodeui)

Limitation: this is a plain HTTP proxy (no WebSocket upgrade), so the chat's
live stream won't run through it. Use the Docker stack (./start.sh) for that.
Backends are configured via env: AUTH_URL, FILES_URL, AGENT_URL, ROUTER_PORT.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

AUTH_URL = os.environ.get("AUTH_URL", "http://127.0.0.1:8091")
FILES_URL = os.environ.get("FILES_URL", "http://127.0.0.1:8092")
AGENT_URL = os.environ.get("AGENT_URL", "http://127.0.0.1:3001")
PORT = int(os.environ.get("ROUTER_PORT", "8080"))

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host",
}


def _is_public(path: str) -> bool:
    return path == "/login" or path.startswith("/api/auth/")


def _pick_backend(path: str) -> str:
    if path == "/admin" or path.startswith("/admin/") or path.startswith("/api/admin/"):
        return AUTH_URL
    if path == "/files" or path.startswith("/files/") or path.startswith("/api/files/"):
        return FILES_URL
    return AGENT_URL


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logs
        pass

    # All verbs share one implementation.
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def _handle(self):
        # Routing decisions use the PATH only; the query string (e.g. ?next=...)
        # must not affect matching, or /login?next=/ would look non-public and
        # loop the redirect.
        path = self.path.split("?", 1)[0]
        if _is_public(path):
            return self._proxy(AUTH_URL)

        # forward_auth gate
        ident = self._verify()
        if ident is None:
            nxt = quote(self.path, safe="/")
            self.send_response(302)
            self.send_header("Location", f"/login?next={nxt}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._proxy(_pick_backend(path), extra_headers=ident)

    def _verify(self):
        """Call auth-service /api/auth/verify with the client's cookies."""
        req = urllib.request.Request(f"{AUTH_URL}/api/auth/verify", method="GET")
        cookie = self.headers.get("Cookie")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {
                    "X-Auth-User": resp.headers.get("X-Auth-User", ""),
                    "X-Auth-User-Id": resp.headers.get("X-Auth-User-Id", ""),
                    "X-Auth-Is-Admin": resp.headers.get("X-Auth-Is-Admin", "0"),
                }
        except urllib.error.HTTPError:
            return None
        except urllib.error.URLError:
            return None

    def _proxy(self, base: str, extra_headers: dict | None = None):
        body = None
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            body = self.rfile.read(length)

        req = urllib.request.Request(base + self.path, data=body, method=self.command)
        for k, v in self.headers.items():
            if k.lower() not in _HOP_BY_HOP:
                req.add_header(k, v)
        for k, v in (extra_headers or {}).items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in _HOP_BY_HOP:
                        self.send_header(k, v)
                payload = resp.read()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as e:
            payload = e.read()
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in _HOP_BY_HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except urllib.error.URLError as e:
            msg = f"backend unreachable: {base} ({e})".encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


if __name__ == "__main__":
    print(f"dev-router on http://127.0.0.1:{PORT}")
    print(f"  auth  -> {AUTH_URL}\n  files -> {FILES_URL}\n  agent -> {AGENT_URL}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
