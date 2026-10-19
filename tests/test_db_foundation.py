# -*- coding: utf-8 -*-
"""Phase 3 / branch 1 — قواعد RTDB (فهارس)، استعلامات الـ fake، _fb_query، وإعادة المحاولة (INFO-004)."""
import json
import logging
import pathlib

import pytest

from tests import fakes

ROOT = pathlib.Path(__file__).resolve().parent.parent
ORDERS = "data/1001/orders"


# ── database.rules.json ──────────────────────────────────
def test_rules_file_locks_clients_and_defines_indexes():
    rules = json.loads((ROOT / "database.rules.json").read_text(encoding="utf-8"))["rules"]
    assert rules[".read"] is False and rules[".write"] is False
    assert set(rules["data"]["$uid"]["orders"][".indexOn"]) == {"createdAt", "updatedAt", "phoneDigits"}
    assert rules["conversations_meta"]["$uid"][".indexOn"] == ["lastTimestamp"]
    assert rules["support_tickets"][".indexOn"] == ["uid"]


# ── الـ fake يتصرف كيما RTDB ─────────────────────────────
@pytest.fixture
def orders(db):
    db.set(ORDERS, {
        "o1": {"createdAt": 100, "updatedAt": 500, "phoneDigits": "0555"},
        "o2": {"createdAt": 200, "updatedAt": 300, "phoneDigits": "0666"},
        "o3": {"createdAt": 300, "updatedAt": 300, "phoneDigits": "0555"},
        "o4": {"phoneDigits": "0777"},  # بلا createdAt → يجي الأول فالترتيب
    })


def _q(path, child):
    ref = fakes.FakeReference(path)
    return ref.order_by_key() if child == "$key" else ref.order_by_child(child)


def test_order_by_child_sorts_like_rtdb(orders):
    assert list(_q(ORDERS, "createdAt").get()) == ["o4", "o1", "o2", "o3"]
    # نفس القيمة → الترتيب بالمفتاح
    assert list(_q(ORDERS, "updatedAt").start_at(300).get()) == ["o2", "o3", "o1"]


def test_equal_to_start_end_and_limit(orders):
    assert list(_q(ORDERS, "phoneDigits").equal_to("0555").get()) == ["o1", "o3"]
    assert list(_q(ORDERS, "createdAt").start_at(150).end_at(300).get()) == ["o2", "o3"]
    assert list(_q(ORDERS, "createdAt").limit_to_last(2).get()) == ["o2", "o3"]
    assert list(_q(ORDERS, "createdAt").limit_to_first(1).get()) == ["o4"]


def test_unindexed_child_query_is_rejected_like_rest(orders):
    with pytest.raises(fakes.InvalidArgumentError, match="Index not defined"):
        _q(ORDERS, "status").equal_to("Pending").get()
    with pytest.raises(fakes.InvalidArgumentError):
        _q("users", "Username").equal_to("x").get()


def test_order_by_key_needs_no_index(db):
    db.set("data/1001/auditLog", {"-a1": {"x": 1}, "-a2": {"x": 2}, "-a3": {"x": 3}})
    q = _q("data/1001/auditLog", "$key")
    assert list(q.limit_to_last(2).get()) == ["-a2", "-a3"]
    assert list(_q("data/1001/auditLog", "$key").start_at("-a2").get()) == ["-a2", "-a3"]


def test_shallow_get_returns_keys_only(orders):
    assert fakes.FakeReference(ORDERS).get(shallow=True) == {"o1": True, "o2": True, "o3": True, "o4": True}


def test_reads_are_recorded(orders):
    fakes.FakeReference(ORDERS).get()
    _q(ORDERS, "phoneDigits").equal_to("0555").get()
    assert fakes.READS[0] == ("get", "/" + ORDERS, {})
    kind, path, order_by, params = fakes.READS[1]
    assert (kind, path, order_by, params["equal_to"]) == ("query", "/" + ORDERS, "phoneDigits", "0555")


# ── _fb_query فـ app.py ──────────────────────────────────
def test_fb_query_returns_ordered_results(app, orders):
    assert list(app._fb_query(ORDERS, "phoneDigits", equal_to="0555")) == ["o1", "o3"]
    assert list(app._fb_query(ORDERS, "createdAt", start_at=150, limit_last=1)) == ["o3"]
    assert list(app._fb_query(ORDERS, "$key", limit_last=2)) == ["o3", "o4"]
    assert app._fb_query("data/1001/nothing", "$key", limit_last=5) == {}


def test_fb_query_returns_none_and_logs_on_missing_index(app, orders, caplog):
    caplog.set_level(logging.ERROR)
    assert app._fb_query(ORDERS, "status", equal_to="Pending") is None
    assert "Index not defined" in caplog.text


# ── INFO-004: إعادة المحاولة على الأخطاء المؤقتة فقط ──────────────
class UnavailableError(Exception):
    """نفس اسم firebase_admin.exceptions.UnavailableError (HTTP 503 / انقطاع)."""


@pytest.fixture
def no_sleep(app, monkeypatch):
    slept = []
    monkeypatch.setattr(app, "sleep", lambda s: slept.append(s))
    return slept


def _flaky(monkeypatch, method, exc, fail_times=1):
    calls = {"n": 0}
    real = getattr(fakes.FakeReference, method)

    def wrapper(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc
        return real(self, *a, **kw)

    monkeypatch.setattr(fakes.FakeReference, method, wrapper)
    return calls


def test_get_retries_once_on_transient_error(app, db, monkeypatch, no_sleep):
    db.set("x/y", {"a": 1})
    calls = _flaky(monkeypatch, "get", UnavailableError("503"))
    assert app._fb_get("x/y") == {"a": 1}
    assert calls["n"] == 2 and no_sleep == [0.5]


def test_set_and_update_retry_once(app, db, monkeypatch, no_sleep):
    _flaky(monkeypatch, "set", UnavailableError("503"))
    assert app._fb_put("x/y", {"a": 1}) is True
    _flaky(monkeypatch, "update", UnavailableError("503"))
    assert app._fb_patch("x/y", {"b": 2}) is True
    assert db.get("x/y") == {"a": 1, "b": 2}


def test_no_retry_on_non_transient_error(app, monkeypatch, no_sleep):
    calls = _flaky(monkeypatch, "get", fakes.InvalidArgumentError("400"))
    assert app._fb_get("x/y") is None
    assert calls["n"] == 1 and no_sleep == []


def test_gives_up_after_one_retry(app, monkeypatch, no_sleep):
    calls = _flaky(monkeypatch, "get", UnavailableError("503"), fail_times=5)
    assert app._fb_get("x/y") is None
    assert calls["n"] == 2


def test_push_is_not_retried(app, monkeypatch, no_sleep):
    """push ماشي idempotent: إذا الطلب الأول وصل، إعادة المحاولة تكتب نسخة ثانية."""
    calls = _flaky(monkeypatch, "push", UnavailableError("503"))
    assert app._fb_push("x", {"a": 1}) is None
    assert calls["n"] == 1


def test_firebase_ref_no_longer_retries_reference(app, monkeypatch, no_sleep):
    """db.reference() ما يتصلش بالشبكة — إعادة المحاولة عليه كانت تضيّع ثانيتين بلا فايدة."""
    assert app._fb_get("bad.path") is None
    assert no_sleep == []
