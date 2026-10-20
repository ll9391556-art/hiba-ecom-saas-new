# -*- coding: utf-8 -*-
"""Phase 4 / A9 — صفحات HTML (/admin، /privacy، /lp/<id>، نوافذ OAuth) خاصها تبقى نفسها
بالضبط بعد النقل لـ templates/. الملفات فـ tests/golden/ تولّدات من الكود قبل A9 (commit
7af0e8a) بـ UPDATE_GOLDEN=1؛ هاد الاختبار يقارنها بايت ببايت."""
import os
import pathlib

import pytest

from tests.test_oauth_callback import FakeResp, _full_url

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"
HTTPS = "https://localhost"
TRICKY = 'متجر "أمينة" & <b>Co</b> </script>'

LANDINGS = {
    "lp_full": {
        "name": "Sac <Cuir>", "headline": "أحسن صاك 'فالجزائر'", "subheadline": "جودة & ضمان",
        "description": "سطر 1\nسطر 2 <script>alert(1)</script>",
        "images": ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg?x=1&y=2", "javascript:alert(1)"],
        "benefits": ["جلد طبيعي", "<i>خفيف</i>", ""], "urgencyText": "باقي 3 فقط!",
        "guaranteeText": "استرجاع 7 أيام", "faq": [{"q": "التوصيل؟", "a": "58 ولاية <b>كاملة</b>"}, {"q": ""}],
        "ctaType": "whatsapp", "whatsappNumber": "+213 555-12-34-56", "published": True,
    },
    "lp_minimal": {"name": "Robe", "published": True},
    "lp_one_image": {"name": "Montre", "images": ["https://cdn.test/m.png"], "ctaType": "store",
                     "description": "وصف قصير", "published": True},
}


def _check(name, html):
    path = GOLDEN / f"{name}.html"
    data = html.encode("utf-8")
    if UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_bytes(data)
        return
    expected = path.read_bytes()
    if data != expected:
        same_ws = b"".join(data.split()) == b"".join(expected.split())
        pytest.fail(f"{name}: rendered HTML differs from golden "
                    f"({'whitespace only' if same_ws else 'CONTENT differs'})")


def test_admin_page(client):
    r = client.get("/admin")
    assert r.status_code == 200
    _check("admin", r.get_data(as_text=True))


def test_privacy_page(client):
    r = client.get("/privacy")
    assert r.status_code == 200
    _check("privacy", r.get_data(as_text=True))


@pytest.mark.parametrize("name", sorted(LANDINGS))
def test_landing_pages(client, db, seed_owner, name):
    owner = seed_owner()
    uid = owner["uid"]
    db.set(f"data/{uid}/storeSettings", {"name": TRICKY, "currency": "DZD"})
    pid = f"LP{uid}T1700000000000"
    db.set(f"data/{uid}/landingPages/{pid}", LANDINGS[name])
    r = client.get(f"/lp/{pid}")
    assert r.status_code == 200
    _check(name, r.get_data(as_text=True))


@pytest.mark.parametrize("name,url", [
    ("oauth_error_cancel", "/callback?error=access_denied"),
    ("oauth_error_missing", "/callback"),
    ("oauth_error_bad_state", "/callback?code=x&state=not-a-jwt"),
])
def test_oauth_error_pages(client, name, url):
    _check(name, client.get(url, base_url=HTTPS).get_data(as_text=True))


def test_oauth_error_page_escaping(app):
    _check("oauth_error_tricky", app._oauth_error_page(TRICKY))


@pytest.fixture
def graph(monkeypatch, app):
    pages = {"data": [
        {"id": "PAGE1", "name": 'صفحة "أمينة" <b>&</b>', "access_token": "page-tok-789",
         "instagram_business_account": {"id": "IG1"}},
        {"id": "PAGE2", "name": "Shop 2", "access_token": "page-tok-2"},
    ]}

    def fake_get(url, params=None, timeout=None, **kw):
        if url.endswith("/me/accounts"):
            return FakeResp(200, pages, _full_url(url, params))
        tok = "short-tok-123" if "fb_exchange_token" not in (params or {}) else "long-tok-456"
        return FakeResp(200, {"access_token": tok}, _full_url(url, params))

    monkeypatch.setattr(app.requests, "get", fake_get)


def test_oauth_success_page(client, seed_owner, graph):
    owner = seed_owner()
    state = client.get("/api/getOAuthState", headers=owner["headers"], base_url=HTTPS).get_json()["data"]["state"]
    r = client.get(f"/callback?code=x&state={state}", base_url=HTTPS)
    assert "FB_AUTH_SUCCESS" in r.get_data(as_text=True)
    _check("oauth_success", r.get_data(as_text=True))


def test_oauth_success_without_pages(client, seed_owner, monkeypatch, app):
    owner = seed_owner()

    def fake_get(url, params=None, timeout=None, **kw):
        if url.endswith("/me/accounts"):
            return FakeResp(200, {"data": []}, _full_url(url, params))
        return FakeResp(200, {"access_token": "tok"}, _full_url(url, params))

    monkeypatch.setattr(app.requests, "get", fake_get)
    state = client.get("/api/getOAuthState", headers=owner["headers"], base_url=HTTPS).get_json()["data"]["state"]
    _check("oauth_success_no_pages", client.get(f"/callback?code=x&state={state}", base_url=HTTPS)
           .get_data(as_text=True))
