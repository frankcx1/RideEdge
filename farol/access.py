"""Personal API credentials: only a verifier is stored on the workstation.

Provision/rotate from an interactive operator terminal with `python -m
farol.access issue`. No credentials in URLs, APK constants, logs or fixtures.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from farol.dashboard import ROOT
from farol.browser_access import BrowserAccess

COOKIE = "__Host-rideedge"
TOKEN = re.compile(r"re_[A-Za-z0-9_-]{43}\Z")
PUBLIC_ORIGIN = "https://rideedge.example.com"


class AccessPolicy:
    def __init__(self, path: Path | None = None, origin: str | None = None):
        self.path = path or ROOT / ".cache/runtime/access.json"
        self.origin = (origin or os.getenv("RIDEEDGE_PUBLIC_ORIGIN", PUBLIC_ORIGIN)).rstrip("/")
        parsed = urlsplit(self.origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("RideEdge public origin must be one HTTPS origin")
        self.host = parsed.netloc

    def digest(self):
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            value = saved.get("token_digest", "")
            if saved.get("schema") == 1 and isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value):
                return value
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def verify(self, token):
        digest = self.digest()
        return bool(digest and isinstance(token, str) and TOKEN.fullmatch(token)
                    and hmac.compare_digest(digest, hashlib.sha256(token.encode("ascii")).hexdigest()))

    def verify_browser(self, token):
        return self.verify(token) or BrowserAccess(self.path).verify(token, self.digest(), self.origin)

    def secure_browser(self, request):
        # Uvicorn proxy_headers=False preserves the actual socket peer. Only the
        # loopback reverse proxy may assert TLS termination. Deployment also
        # removes the HTTP Serve route; this is not a tailnet ACL substitute.
        peer = request.client.host if request.client else ""
        return request.headers.get("host") == self.host and (
            request.url.scheme == "https" or (
                peer in {"127.0.0.1", "::1"} and request.headers.get("x-forwarded-proto") == "https"
            ))

    def direct_operator(self, request):
        peer = request.client.host if request.client else ""
        return (peer in {"127.0.0.1", "::1"} and
                request.url.hostname in {"127.0.0.1", "::1", "localhost"} and
                not any(key in request.headers for key in ("forwarded", "x-forwarded-for", "x-forwarded-proto", "origin")))

    def check(self, request):
        if self.digest() is None:
            return "setup_required"
        auth = request.headers.get("authorization", "")
        if auth:
            if not (self.secure_browser(request) or self.direct_operator(request)):
                return "secure_connection_required"
            return "allowed" if auth.startswith("Bearer ") and self.verify(auth[7:]) else "unauthorized"
        if not self.secure_browser(request):
            return "secure_connection_required"
        if not self.verify_browser(request.cookies.get(COOKIE)):
            return "unauthorized"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("origin") != self.origin:
            return "origin_rejected"
        return "allowed"


def issue(path: Path):
    """Atomic replacement revokes the previous phone/browser key immediately."""
    token = "re_" + secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"schema": 1, "token_digest": hashlib.sha256(token.encode("ascii")).hexdigest()}), encoding="utf-8")
    temporary.replace(path)
    return token


def login_page():
    nonce = secrets.token_urlsafe(24)
    html = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Connect to RideEdge</title>
<style>body{background:#091118;color:#edf5f8;font:18px system-ui;max-width:32rem;margin:10vh auto;padding:24px}
input,button{box-sizing:border-box;width:100%;padding:14px;margin:12px 0;font:inherit}button{background:#00d5b2;border:0;border-radius:8px}
p{line-height:1.5;color:#b5c5cf}</style><h1>Connect to RideEdge</h1>
<p>On workstation, run <code>.&#92;scripts&#92;open-studio.ps1</code> to copy a temporary dashboard key, then paste it below. Your existing RideEdge key also works.</p>
<form id="login"><label for="key">Access key</label><input id="key" type="password" autocomplete="current-password" maxlength="46" required>
<button>Connect</button></form><p id="status" role="status"></p>
<script nonce="NONCE">document.getElementById('login').onsubmit=async(e)=>{e.preventDefault();
const input=document.getElementById('key'),status=document.getElementById('status');
try{const result=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:input.value.trim()})});
input.value='';if(result.ok){location.replace('/studio');}else{status.textContent='Could not connect. Check the access key and server setup.';}}
catch{input.value='';status.textContent='workstation could not be reached.';}};</script></html>""".replace("NONCE", nonce)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})


class AccessMiddleware:
    def __init__(self, app, policy=None):
        self.app = app
        self.policy = policy or AccessPolicy()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        path = scope["path"]
        if path == "/api/live" and request.method in {"GET", "HEAD"}:
            await JSONResponse({"status": "alive"}, headers={"Cache-Control": "no-store"})(scope, receive, send)
            return
        if path == "/auth/login" and request.method == "GET":
            response = login_page() if self.policy.secure_browser(request) else RedirectResponse(self.policy.origin + "/auth/login", 303)
            await response(scope, receive, send)
            return
        if path == "/auth/login" and request.method == "POST":
            response = await self.login(request)
            await response(scope, receive, send)
            return
        decision = self.policy.check(request)
        if decision != "allowed":
            if not path.startswith(("/api/", "/auth/")) and request.method == "GET":
                response = RedirectResponse(self.policy.origin + "/auth/login", 303)
            else:
                response = JSONResponse({"detail": "Connect RideEdge with its access key.", "code": decision},
                    status_code=503 if decision == "setup_required" else 401,
                    headers={"Cache-Control": "no-store", "WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        if path == "/auth/check":
            await JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})(scope, receive, send)
            return
        if path == "/auth/logout" and request.method == "POST":
            response = JSONResponse({"signed_out": True}, headers={"Cache-Control": "no-store"})
            response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
            await response(scope, receive, send)
            return

        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)
        await self.app(scope, receive, private_send)

    async def login(self, request):
        invalid = JSONResponse({"detail": "Access key or secure connection unavailable."}, 401, headers={"Cache-Control": "no-store"})
        if (not self.policy.secure_browser(request) or request.headers.get("origin") != self.policy.origin or
                request.headers.get("content-type", "").split(";")[0] != "application/json"):
            return invalid
        try:
            raw = bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 1024:
                        return invalid
            body = json.loads(raw)
            token = body.get("token")
        except (ValueError, AttributeError, TimeoutError):
            return invalid
        if not self.policy.verify_browser(token):
            return invalid
        response = JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})
        response.set_cookie(COOKIE, token, max_age=43200, secure=True, httponly=True, samesite="strict", path="/")
        return response


def main():
    parser = argparse.ArgumentParser(description="RideEdge local access-key provisioning")
    parser.add_argument("command", choices=["issue", "status", "revoke"])
    args = parser.parse_args()
    policy = AccessPolicy()
    if args.command == "status":
        print("Access key configured" if policy.digest() else "Access key missing or invalid; protected routes fail closed")
    elif args.command == "revoke":
        policy.path.unlink(missing_ok=True)
        print("Access revoked. Provision a new key before reconnecting clients.")
    else:
        if not sys.stdout.isatty():
            raise SystemExit("Issue keys in an interactive terminal; do not capture them in logs or tool output.")
        print("New access key (replaces the previous key; copy into Connection on the phone):")
        print(issue(policy.path))


if __name__ == "__main__":
    main()
