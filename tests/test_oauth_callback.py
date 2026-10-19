# -*- coding: utf-8 -*-
"""SEC-001 — /callback ما يكشفش client_secret ولا التوكنات فصفحة الخطأ ولا فالسجلات."""
import logging
import time

import pytest
import requests

SECRET = "dummy-secret"  # = FB_APP_SECRET فـ conftest


class FakeResp:
    def __init__(self, status, payload=None, url=""):
        self.status_code = status
        self.ok = 200 <= status < 400
        self._payload = payload or {}
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self):
        # نفس نص requests.HTTPError الحقيقي — يحتوي الـ URL الكامل بالـ query
        if not self.ok:
            raise requests.HTTPError(
                f"{self.status_code} Client Error: Bad Request for url: {self.url}", response=self)


def _full_url(url, params):
    return requests.Request("GET", url, params=params).prepare().url


@pytest.fixture
def graph(monkeypatch, app):
    """يستبدل requests.get بسلسلة ردود (أو استثناءات) بالترتيب."""
    queue = []

    def fake_get(url, params=None, timeout=None, **kw):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item
        return FakeResp(status, payload, _full_url(url, params))

    monkeypatch.setattr(app.requests, "get", fake_get)
    return queue


def _valid_state(app, owner):
    return app.jwt.encode({"uid": owner["uid"], "uname": owner["username"],
                           "exp": int(time.time()) + 600}, app.JWT_SECRET, algorithm=app.JWT_ALGO)


def _assert_no_leak(body, caplog, *extra):
    for needle in (SECRET, "client_secret", *extra):
        assert needle not in body, f"{needle!r} leaked in response"
        assert needle not in caplog.text, f"{needle!r} leaked in logs"


def test_code_exchange_400_does_not_leak_secret(client, graph, caplog):
    caplog.set_level(logging.INFO)
    graph.append((400, {"error": {"message": "Invalid verification code format."}}))
    r = client.get("/callback?code=x&state=y")
    _assert_no_leak(r.get_data(as_text=True), caplog)
    assert "FB_AUTH_ERROR" in r.get_data(as_text=True)


def test_network_error_does_not_leak_secret(client, graph, caplog):
    caplog.set_level(logging.INFO)
    graph.append(requests.ConnectionError(
        "HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries exceeded with url: "
        f"/v19.0/oauth/access_token?client_id=0&client_secret={SECRET}&code=x"))
    r = client.get("/callback?code=x&state=y")
    _assert_no_leak(r.get_data(as_text=True), caplog)


def test_long_lived_exchange_failure_does_not_leak_secret(client, graph, caplog):
    caplog.set_level(logging.INFO)
    graph.extend([(200, {"access_token": "short-tok-123"}), (400, {})])
    r = client.get("/callback?code=x&state=y")
    _assert_no_leak(r.get_data(as_text=True), caplog, "short-tok-123")


def test_accounts_failure_does_not_leak_user_token(client, graph, caplog):
    caplog.set_level(logging.INFO)
    graph.extend([(200, {"access_token": "short-tok-123"}),
                  (200, {"access_token": "long-tok-456"}), (400, {})])
    r = client.get("/callback?code=x&state=y")
    _assert_no_leak(r.get_data(as_text=True), caplog, "long-tok-456")


def test_successful_connection_still_saves_tokens(app, client, db, graph, seed_owner):
    owner = seed_owner()
    graph.extend([
        (200, {"access_token": "short-tok-123"}),
        (200, {"access_token": "long-tok-456"}),
        (200, {"data": [{"id": "PAGE1", "name": "Shop", "access_token": "page-tok-789",
                         "instagram_business_account": {"id": "IG1"}}]}),
    ])
    r = client.get(f"/callback?code=x&state={_valid_state(app, owner)}")
    assert r.status_code == 200
    assert "FB_AUTH_SUCCESS" in r.get_data(as_text=True)
    saved = db.get(f"data/{owner['uid']}/fbTokens")
    assert saved["fb_page_id"] == "PAGE1" and saved["Page_ID_instgram"] == "IG1"
    assert saved["fb_access_token"] == "page-tok-789"
    assert db.get("channel_index/PAGE1") == owner["username"]
    assert db.get("channel_index/IG1") == owner["username"]


def test_invalid_state_shows_fixed_message(client, graph, caplog):
    graph.extend([(200, {"access_token": "s"}), (200, {"access_token": "l"}), (200, {"data": []})])
    r = client.get("/callback?code=x&state=not-a-jwt")
    body = r.get_data(as_text=True)
    assert "FB_AUTH_ERROR" in body
    assert "UID missing" not in body
