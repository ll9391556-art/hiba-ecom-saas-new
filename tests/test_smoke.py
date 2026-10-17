# -*- coding: utf-8 -*-
"""اختبارات دخان للبنية التحتية — لا تغيّر ولا تختبر أي إصلاح بعد."""
import socket

import pytest

from tests import fakes
from tests.fakes import NetworkBlocked


def test_app_imports_and_blueprints_registered(app):
    rules = {r.rule for r in app.app.url_map.iter_rules()}
    for expected in ("/health", "/api/login", "/api/saas", "/callback", "/webhook",
                     "/api/coupons/list", "/api/tracking/public", "/api/support/submit",
                     "/api/shipping/connect", "/api/assistant/ask", "/api/multistore/list"):
        assert expected in rules


def test_health_returns_200(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_network_is_blocked():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443))


def test_fake_db_semantics(db):
    ref = fakes.FakeReference("a/b")
    ref.set({"x": 1, "empty": {}})
    assert db.get("a/b") == {"x": 1}          # القواميس الفارغة لا تُخزَّن
    fakes.FakeReference("a/b").update({"y": 2})
    assert db.get("a//b") == {"x": 1, "y": 2}  # المقاطع الفارغة تُحذف
    key = fakes.FakeReference("a/list").push({"v": 1}).key
    assert db.get(f"a/list/{key}") == {"v": 1}
    assert fakes.FakeReference("a/n").transaction(lambda c: (c or 0) + 1) == 1
    fakes.FakeReference("a/b").delete()
    assert db.get("a/b") is None
    with pytest.raises(ValueError):
        fakes.FakeReference("a/b.c")


def test_protected_route_requires_token(client):
    r = client.get("/api/getOrders")
    assert r.status_code == 401


def test_owner_reads_own_orders(client, db, seed_owner):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/orders/ORD-1", {"id": "ORD-1", "status": "Pending"})
    r = client.get("/api/getOrders", headers=owner["headers"])
    assert r.status_code == 200
    assert [o["id"] for o in r.get_json()["data"]] == ["ORD-1"]


def test_member_without_perm_gets_403(client, seed_owner, seed_member):
    member = seed_member(seed_owner(), perms={"orders": False})
    assert client.get("/api/getOrders", headers=member["headers"]).status_code == 403


def test_deleted_member_gets_401(client, db, seed_owner, seed_member):
    member = seed_member(seed_owner(), perms={"orders": True})
    db.set(f"team_users/{member['username']}", None)
    assert client.get("/api/getOrders", headers=member["headers"]).status_code == 401


def test_owner_login_with_bcrypt(client, seed_owner):
    owner = seed_owner()
    r = client.post("/api/login", json={"username": owner["username"], "password": owner["password"]})
    assert r.status_code == 200
    body = r.get_json()["data"]
    assert body["role"] == "owner" and body["token"]
    assert "Password" not in body
