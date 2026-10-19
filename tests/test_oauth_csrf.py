# -*- coding: utf-8 -*-
"""SEC-004 — state مربوط بالمتصفح بـ nonce فكوكي HttpOnly (استعمال واحد)، وpostMessage
بلا توكنات ولا "*"."""
import pathlib
import re

import pytest

from tests.test_oauth_callback import FakeResp, _full_url

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTTPS = "https://localhost"
COOKIE = "of_oauth_nonce"
PAGES = {"data": [{"id": "PAGE1", "name": "Shop", "access_token": "page-tok-789",
                   "instagram_business_account": {"id": "IG1"}}]}


@pytest.fixture
def graph(monkeypatch, app):
    calls = []

    def fake_get(url, params=None, timeout=None, **kw):
        calls.append(url)
        if url.endswith("/me/accounts"):
            return FakeResp(200, PAGES, _full_url(url, params))
        tok = "short-tok-123" if "fb_exchange_token" not in (params or {}) else "long-tok-456"
        return FakeResp(200, {"access_token": tok}, _full_url(url, params))

    monkeypatch.setattr(app.requests, "get", fake_get)
    return calls


@pytest.fixture
def owner(seed_owner):
    return seed_owner()


def _start(client, owner):
    """زي ما تدير الواجهة: تطلب state (والسيرفر يحط الكوكي فنفس الرد)."""
    r = client.get("/api/getOAuthState", headers=owner["headers"], base_url=HTTPS)
    assert r.status_code == 200
    return r, r.get_json()["data"]["state"]


def _callback(client, state):
    return client.get(f"/callback?code=x&state={state}", base_url=HTTPS)


def _set_cookies(resp):
    return [v for k, v in resp.headers.items() if k.lower() == "set-cookie" and v.startswith(COOKIE + "=")]


def test_get_state_sets_strict_nonce_cookie(client, owner):
    r, _ = _start(client, owner)
    (cookie,) = _set_cookies(r)
    flags = cookie.lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/callback"):
        assert flag in flags
    assert re.search(r"max-age=600\b", flags)


def test_callback_without_cookie_rejected_before_graph(client, db, owner, graph):
    _, state = _start(client, owner)
    client.delete_cookie(COOKIE, path="/callback")
    body = _callback(client, state).get_data(as_text=True)
    assert "FB_AUTH_ERROR" in body
    assert graph == []
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_callback_with_wrong_cookie_rejected(client, db, owner, graph):
    _, state = _start(client, owner)
    client.set_cookie(COOKIE, "attacker-nonce", path="/callback")
    assert "FB_AUTH_ERROR" in _callback(client, state).get_data(as_text=True)
    assert graph == [] and db.get(f"data/{owner['uid']}/fbTokens") is None


def test_valid_flow_saves_and_is_single_use(client, db, owner, graph):
    _, state = _start(client, owner)
    r = _callback(client, state)
    assert "FB_AUTH_SUCCESS" in r.get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens")["fb_page_id"] == "PAGE1"
    pending = db.get(f"oauth_pending/{owner['uid']}")
    assert "nh" not in pending and "used" in pending  # مستهلك: علامة بلا nh
    # replay: نفس state ونفس الكوكي (حتى لو المهاجم عاود حطّها)
    db.set(f"data/{owner['uid']}/fbTokens", None)
    client.set_cookie(COOKIE, "ignored", path="/callback")
    assert "FB_AUTH_ERROR" in _callback(client, state).get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_replay_with_original_cookie_rejected(client, db, owner, graph):
    r, state = _start(client, owner)
    nonce = _set_cookies(r)[0].split(";")[0].split("=", 1)[1]
    _callback(client, state)
    db.set(f"data/{owner['uid']}/fbTokens", None)
    client.set_cookie(COOKIE, nonce, path="/callback")
    assert "FB_AUTH_ERROR" in _callback(client, state).get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_older_state_rejected_after_new_attempt(client, db, owner, graph):
    r_old, old_state = _start(client, owner)
    old_nonce = _set_cookies(r_old)[0].split(";")[0].split("=", 1)[1]
    _start(client, owner)  # ضغطة ثانية على "ربط"
    client.set_cookie(COOKIE, old_nonce, path="/callback")
    assert "FB_AUTH_ERROR" in _callback(client, old_state).get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_every_callback_response_clears_cookie(client, owner, graph):
    _, state = _start(client, owner)
    for resp in (_callback(client, state), _callback(client, "bad"),
                 client.get("/callback?error=access_denied", base_url=HTTPS)):
        (cookie,) = _set_cookies(resp)
        assert re.search(r"max-age=0\b", cookie.lower()) or "expires=thu, 01 jan 1970" in cookie.lower()


def _script(body):
    return body[body.index("<script>"):]


def test_success_page_posts_no_tokens_and_no_wildcard(client, owner, graph):
    _, state = _start(client, owner)
    script = _script(_callback(client, state).get_data(as_text=True))
    for secret in ("page-tok-789", "long-tok-456", "short-tok-123", "PAGE1", "IG1"):
        assert secret not in script
    assert '"*"' not in script and "'*'" not in script
    assert '{type:"FB_AUTH_SUCCESS"}' in script
    assert '"https://orderconfidence.com"' in script


def test_error_page_has_no_wildcard_target(client):
    script = _script(client.get("/callback?error=access_denied").get_data(as_text=True))
    assert "FB_AUTH_ERROR" in script
    assert '"*"' not in script and "'*'" not in script
    assert '"https://orderconfidence.com"' in script


def test_get_state_cors_allows_credentials_for_allowed_origin(client, owner):
    r = client.get("/api/getOAuthState", headers={**owner["headers"], "Origin": "https://orderconfidence.com"},
                   base_url=HTTPS)
    assert r.headers.get("Access-Control-Allow-Origin") == "https://orderconfidence.com"
    assert r.headers.get("Access-Control-Allow-Credentials") == "true"
    other = client.get("/api/getOAuthState", headers={**owner["headers"], "Origin": "https://evil.test"},
                       base_url=HTTPS)
    assert "Access-Control-Allow-Origin" not in other.headers


def test_frontend_checks_origin_and_reloads_from_server():
    src = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    fn = src[src.index("async function connectFacebook"):]
    fn = fn[:fn.index("\nasync function ")]
    assert "ev.origin!==FB_ORIGIN" in fn.replace(" ", "")
    assert "ev.source!==win" in fn.replace(" ", "")
    assert 'credentials:"include"' in fn.replace(" ", "")
    assert "loadBot()" in fn and "loadSettings()" in fn
    for field in ("fb_token", "ig_token", "fb_page_id", "ig_page_id"):
        assert field not in fn
