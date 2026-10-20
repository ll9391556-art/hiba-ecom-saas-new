# -*- coding: utf-8 -*-
"""اللوحة تعاود تفتح بعد reload من of_token عبر /api/me — بلا ما تخرّج صاحبة الحساب."""
import pathlib
import re
import time

from tests.frontend import dashboard_and_shop

from tests.conftest import auth

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = dashboard_and_shop()  # HTML + /static/js/* (Phase 4 / F1)
SECRET_KEYS = ("Password", "Gemini_api_key", "fb_access_token", "instgram_access_token", "whtsapp_token")


def test_me_returns_owner_identity_without_secrets(client, seed_owner):
    owner = seed_owner(Gemini_api_key="dummy-gemini-key", fb_access_token="dummy-fb-tok")
    r = client.get("/api/me", headers=owner["headers"])
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["Username"] == owner["username"] and data["User_ID"] == owner["uid"]
    assert data["role"] == "owner"
    for k in SECRET_KEYS:
        assert k not in data
    assert "dummy-gemini-key" not in r.get_data(as_text=True)


def test_me_returns_member_with_current_permissions(client, db, seed_owner, seed_member):
    owner = seed_owner()
    member = seed_member(owner, perms={"orders": True})
    db.set(f"team_users/{member['username']}/permissions", {"orders": True, "products": True})
    data = client.get("/api/me", headers=member["headers"]).get_json()["data"]
    assert data["role"] == "member" and data["memberUsername"] == member["username"]
    assert data["User_ID"] == owner["uid"]
    assert data["permissions"]["products"] is True  # من قاعدة البيانات، مش من التوكن


def test_me_rejects_disabled_member(client, db, seed_owner, seed_member):
    owner = seed_owner()
    member = seed_member(owner)
    db.set(f"team_users/{member['username']}/active", False)
    assert client.get("/api/me", headers=member["headers"]).status_code == 403


def test_me_rejects_missing_bad_expired_and_state_tokens(client, app, seed_owner):
    owner = seed_owner()
    expired = app.jwt.encode({"uid": owner["uid"], "username": owner["username"], "role": "owner",
                              "typ": "session", "iat": 1, "exp": int(time.time()) - 10},
                             app.JWT_SECRET, algorithm=app.JWT_ALGO)
    state = client.get("/api/getOAuthState", headers=owner["headers"]).get_json()["data"]["state"]
    for headers in ({}, auth("x"), auth(expired), auth(state)):
        assert client.get("/api/me", headers=headers).status_code == 401


def _fn(name):
    start = INDEX.index(f"function {name}(")
    end = INDEX.index("\n}\n", start)
    return INDEX[start:end]


def test_startup_restores_session():
    init = INDEX[INDEX.index("// INIT"):]
    assert "restoreSession();" in init
    fn = _fn("restoreSession").replace(" ", "")
    assert "authToken" in fn and 'API_URL+"/me"' in fn
    assert "enterDashboard(" in fn
    # logout() غير على 401/403 — خطأ شبكة أو 5xx يخلّي التوكن
    assert re.search(r"if\(r\.status===401\|\|r\.status===403\)\{logout\(\);return;\}", fn)
    assert fn.count("logout()") == 1


def test_login_uses_shared_enter_dashboard():
    assert "enterDashboard(" in _fn("doLogin")
    assert 'getElementById("loginPage").style.display="none"' in _fn("enterDashboard").replace(" ", "")


def test_nothing_clears_the_session_on_unload():
    for needle in ("beforeunload", "pagehide", '"unload"', "localStorage.clear("):
        assert needle not in INDEX
    assert INDEX.count('localStorage.removeItem("of_token")') == 1  # فقط فـ logout()
