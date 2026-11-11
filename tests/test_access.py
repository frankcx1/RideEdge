import hashlib
import json
import secrets

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from farol.access import COOKIE, AccessMiddleware, AccessPolicy, issue
from farol.browser_access import BrowserAccess, LIFETIME


@pytest.fixture
def access(tmp_path):
    path = tmp_path / "access.json"
    token = issue(path)
    policy = AccessPolicy(path, "https://rideedge.example.test")
    calls = []
    app = FastAPI()
    app.add_middleware(AccessMiddleware, policy=policy)

    @app.api_route("/api/private", methods=["GET", "POST"])
    def private():
        calls.append("work")
        return {"private": "fixture"}

    return policy, token, app, calls


def test_missing_wrong_and_query_tokens_cannot_reach_work(access):
    policy, token, app, calls = access
    client = TestClient(app, base_url=policy.origin)
    assert client.get("/api/live").json() == {"status": "alive"}
    for method in (client.get, client.post):
        for headers in ({}, {"Authorization": "Bearer " + "re_" + secrets.token_urlsafe(32)}, {"X-Farol-Car-Token": token}):
            result = method("/api/private?token=" + token, headers=headers)
            assert result.status_code == 401
            assert token not in result.text
            assert result.headers["cache-control"] == "no-store"
    assert not calls
    good = client.post("/api/private", headers={"Authorization": "Bearer " + token})
    assert good.status_code == 200 and calls == ["work"]
    assert good.headers["cache-control"] == "no-store"


def test_recording_studio_uses_existing_authentication(access):
    from farol.studio import router
    policy, token, app, _ = access
    app.include_router(router)
    client = TestClient(app, base_url=policy.origin)
    assert client.get("/studio", follow_redirects=False).status_code == 303
    assert client.get("/api/studio").status_code == 401
    headers = {"Authorization": "Bearer " + token}
    page = client.get("/studio", headers=headers)
    data = client.get("/api/studio?mode=replay&step=0", headers=headers)
    assert page.status_code == data.status_code == 200
    assert data.json()["mode"] == "replay"
    assert "origin" not in data.json()
    assert data.headers["cache-control"] == "no-store"


def test_verifier_only_rotation_revocation_and_malformed_config(access):
    policy, token, app, _ = access
    saved = policy.path.read_text()
    assert token not in saved
    assert json.loads(saved)["token_digest"] == hashlib.sha256(token.encode()).hexdigest()
    client = TestClient(app, base_url=policy.origin)
    replacement = issue(policy.path)
    assert not policy.verify(token) and policy.verify(replacement)
    assert client.get("/auth/check", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert client.get("/auth/check", headers={"Authorization": "Bearer " + replacement}).json() == {"authenticated": True}
    for bad in ("[]", "broken", '{"schema": 1, "token_digest": "short"}'):
        policy.path.write_text(bad)
        response = client.get("/api/private", headers={"Authorization": "Bearer " + replacement})
        assert response.status_code == 503
        assert response.json()["code"] == "setup_required"
        assert client.get("/api/live").status_code == 200
    policy.path.unlink()
    assert client.get("/api/private").status_code == 503


def test_cookie_login_origin_checks_logout_and_no_open_redirect(access):
    policy, token, app, calls = access
    client = TestClient(app, base_url=policy.origin)
    page = client.get("/auth/login")
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    for origin in (None, "https://unrelated.example"):
        assert client.post("/auth/login", json={"token": token}, headers={"Origin": origin} if origin else {}).status_code == 401
    result = client.post("/auth/login", json={"token": token}, headers={"Origin": policy.origin})
    cookie = result.headers["set-cookie"]
    assert all(flag in cookie for flag in (COOKIE, "Secure", "HttpOnly", "SameSite=strict", "Path=/"))
    assert token not in result.text
    assert client.get("/api/private").status_code == 200
    assert client.post("/api/private").status_code == 401
    assert client.post("/api/private", headers={"Origin": "https://unrelated.example"}).status_code == 401
    assert client.post("/api/private", headers={"Origin": policy.origin}).status_code == 200
    assert len(calls) == 2
    assert client.post("/auth/logout", headers={"Origin": policy.origin}).status_code == 200
    assert client.get("/api/private").status_code == 401
    redirect = client.get("/untrusted?next=https://unrelated.example", follow_redirects=False)
    assert redirect.headers["location"] == policy.origin + "/auth/login"


def test_transport_headers_do_not_create_an_authentication_bypass(access):
    policy, token, app, calls = access
    auth = {"Authorization": "Bearer " + token}
    remote = TestClient(app, base_url="http://rideedge.example.test", client=("192.0.2.1", 50000))
    assert remote.get("/api/private", headers={**auth, "X-Forwarded-Proto": "https"}).status_code == 401
    local = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    assert local.get("/api/private", headers=auth).status_code == 200
    for extra in ({"Origin": "https://unrelated.example"}, {"X-Forwarded-For": "192.0.2.1"}):
        assert local.get("/api/private", headers={**auth, **extra}).status_code == 401
    proxy = TestClient(app, base_url="http://rideedge.example.test", client=("127.0.0.1", 50000))
    assert proxy.get("/api/private", headers=auth).status_code == 401
    assert proxy.get("/api/private", headers={"X-Forwarded-Proto": "https"}).status_code == 401
    assert proxy.get("/api/private", headers={**auth, "X-Forwarded-Proto": "https"}).status_code == 200
    assert len(calls) == 2


def test_login_bounds_and_no_raw_validation_echo(access):
    policy, token, app, _ = access
    client = TestClient(app, base_url=policy.origin)
    headers = {"Origin": policy.origin, "Content-Type": "application/json"}
    for raw in ("[1]", "broken", json.dumps({"token": "x" * 2000}), json.dumps({"token": [token]})):
        result = client.post("/auth/login", content=raw, headers=headers)
        assert result.status_code == 401 and token not in result.text


def test_desktop_key_login_preserves_phone_and_expires(access, monkeypatch):
    from farol import browser_access
    policy, phone_key, app, _ = access
    original = policy.path.read_bytes()
    now = 1000000.0
    monkeypatch.setattr(browser_access.time, "time", lambda: now)
    store = BrowserAccess(policy.path)
    desktop_key = store.issue(policy.digest(), policy.origin)
    assert policy.path.read_bytes() == original and policy.verify(phone_key)
    assert desktop_key.encode() not in store.path.read_bytes()
    assert not store.verify(desktop_key, policy.digest(), "https://other.example")
    client = TestClient(app, base_url=policy.origin)
    assert client.get("/api/private", headers={"Authorization": "Bearer " + desktop_key}).status_code == 401
    assert client.post("/auth/login", json={"token": desktop_key}).status_code == 401
    result = client.post("/auth/login", json={"token": desktop_key}, headers={"Origin": policy.origin})
    assert result.status_code == 200 and desktop_key not in result.text
    assert client.get("/api/private").status_code == 200
    assert client.post("/api/private").status_code == 401
    now += LIFETIME
    assert client.get("/api/private").status_code == 401
    assert policy.verify(phone_key)


def test_desktop_key_fails_closed_after_rotation_or_missing_store(access):
    policy, phone_key, app, _ = access
    store = BrowserAccess(policy.path)
    desktop_key = store.issue(policy.digest(), policy.origin)
    assert policy.verify_browser(desktop_key)
    issue(policy.path)
    assert not policy.verify_browser(desktop_key)
    desktop_key = store.issue(policy.digest(), policy.origin)
    store.path.write_bytes(b"invalid database")
    assert not policy.verify_browser(desktop_key)
    store.path.unlink()
    assert not policy.verify_browser(desktop_key)
    assert not store.path.exists()


def test_actual_app_blocks_rich_health_sources_model_and_legacy_mutations(monkeypatch, tmp_path):
    from farol import access as module
    from farol import collect
    from farol.api import app

    policy = AccessPolicy(tmp_path / "access.json", "https://rideedge.example.test")
    token = issue(policy.path)
    # The real app already owns its middleware, so substitute only its verifier
    # read. No authentication/transport decision is bypassed in this test.
    monkeypatch.setattr(module.AccessPolicy, "digest", lambda self: hashlib.sha256(token.encode()).hexdigest())
    monkeypatch.setattr(collect, "refresh_once", lambda *a, **kw: pytest.fail("Unauthenticated work started"))
    client = TestClient(app, base_url=module.PUBLIC_ORIGIN)
    for path in ("/api/health", "/api/feeds/health", "/api/seatac/forecast", "/api/radar/status", "/api/history"):
        assert client.get(path).status_code == 401
    for path in ("/api/feeds/refresh", "/api/seatac/forecast", "/api/radar/ask", "/api/shift/start", "/api/history/shifts/start"):
        assert client.post(path, json={}).status_code == 401
    assert client.get("/api/live").json() == {"status": "alive"}
