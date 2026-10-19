# -*- coding: utf-8 -*-
"""SEC-012 — توكن state ديال OAuth ما يخدمش كجلسة، وتوكن الجلسة ما يخدمش كـ state."""
import time

import pytest

from tests.conftest import auth


def _state(client, owner):
    r = client.get("/api/getOAuthState", headers=owner["headers"])
    assert r.status_code == 200
    return r.get_json()["data"]["state"]


@pytest.mark.parametrize("path", ["/api/getDashboard", "/fb-status"])
def test_oauth_state_rejected_as_bearer(client, seed_owner, path):
    owner = seed_owner()
    assert client.get(path, headers=auth(_state(client, owner))).status_code == 401


def test_oauth_state_rejected_by_api_saas(client, seed_owner):
    owner = seed_owner()
    r = client.post("/api/saas", headers=auth(_state(client, owner)),
                    json={"action": "firebaseGet", "path": f"data/{owner['uid']}/orders"})
    assert r.status_code == 401


def test_session_token_rejected_as_oauth_state(client, db, seed_owner, monkeypatch, app):
    owner = seed_owner()
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: pytest.fail("Graph called"))
    r = client.get(f"/callback?code=x&state={owner['token']}")
    assert "FB_AUTH_ERROR" in r.get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_new_session_tokens_have_typ(app, seed_owner):
    owner = seed_owner()
    assert app.jwt.decode(owner["token"], app.JWT_SECRET, algorithms=[app.JWT_ALGO])["typ"] == "session"


def _legacy(app, **claims):
    now = int(time.time())
    return app.jwt.encode({"iat": now, "exp": now + 3600, **claims}, app.JWT_SECRET, algorithm=app.JWT_ALGO)


@pytest.mark.parametrize("path", ["/api/getDashboard", "/api/me"])
def test_session_without_typ_rejected(client, app, seed_owner, path):
    """ما كاينش مرحلة انتقالية: توكن بلا typ يترفض حتى لو فيه role (ما كاين حتى تاجر قديم)."""
    owner = seed_owner()
    tok = _legacy(app, uid=owner["uid"], username=owner["username"], role="owner")
    assert client.get(path, headers=auth(tok)).status_code == 401


@pytest.mark.parametrize("typ", ["admin", ""])
def test_unknown_typ_rejected(client, app, db, seed_owner, monkeypatch, typ):
    owner = seed_owner()
    tok = _legacy(app, uid=owner["uid"], username=owner["username"], uname=owner["username"],
                  role="owner", typ=typ)
    assert client.get("/api/getDashboard", headers=auth(tok)).status_code == 401
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: pytest.fail("Graph called"))
    assert "FB_AUTH_ERROR" in client.get(f"/callback?code=x&state={tok}").get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_state_without_typ_rejected_in_callback(client, app, db, seed_owner, monkeypatch):
    """state بلا typ يترفض حتى مع كوكي nonce مطابقة وخانة oauth_pending صالحة."""
    owner = seed_owner()
    nonce = "dummy-nonce-123"
    nh = app._nonce_hash(nonce)
    db.set(f"oauth_pending/{owner['uid']}", {"nh": nh, "exp": int(time.time()) + 600})
    state = _legacy(app, uid=owner["uid"], uname=owner["username"], nh=nh)
    client.set_cookie("of_oauth_nonce", nonce, path="/callback")
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: pytest.fail("Graph called"))
    r = client.get(f"/callback?code=x&state={state}", base_url="https://localhost")
    assert "FB_AUTH_ERROR" in r.get_data(as_text=True)
    assert db.get(f"data/{owner['uid']}/fbTokens") is None


def test_legacy_state_shaped_token_rejected(client, app, seed_owner):
    owner = seed_owner()
    tok = _legacy(app, uid=owner["uid"], uname=owner["username"])  # شكل state القديم: بلا role
    assert client.get("/api/getDashboard", headers=auth(tok)).status_code == 401
