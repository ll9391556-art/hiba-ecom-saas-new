# -*- coding: utf-8 -*-
"""Phase 3 / branch 3 — getOrders: آخر 200 طلب، "تحميل الأقدم"، وpolling بالتغييرات فقط
(updatedAt) بلا تنزيل كل الطلبات. الواجهة توقف الـ polling كي يكون التبويب مخفي."""
import pathlib
import re

import pytest

from tests import fakes

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
T0 = 1_700_000_000_000


@pytest.fixture
def owner(seed_owner):
    return seed_owner()


def _seed(db, uid, n, start=0):
    for i in range(start, start + n):
        db.set(f"data/{uid}/orders/ORD-{T0 + i}", {
            "id": f"ORD-{T0 + i}", "phone": "0555", "status": "Pending",
            "createdAt": T0 + i * 1000, "updatedAt": T0 + i * 1000, "phoneDigits": "0555"})


def _get(client, owner, **params):
    r = client.get("/api/getOrders", query_string=params, headers=owner["headers"])
    return r.status_code, r.get_json()


def _ids(body):
    return [o["id"] for o in body["data"]]


def _full_order_reads(uid):
    return [r for r in fakes.READS if r == ("get", f"/data/{uid}/orders", {})]


def test_default_returns_latest_200_newest_first(client, db, owner):
    _seed(db, owner["uid"], 205)
    fakes.READS.clear()
    code, body = _get(client, owner)
    assert code == 200 and body["status"] == "ok"
    assert len(body["data"]) == 200 and body["hasMore"] is True
    assert _ids(body)[0] == f"ORD-{T0 + 204}" and _ids(body)[-1] == f"ORD-{T0 + 5}"
    assert _full_order_reads(owner["uid"]) == []


def test_load_older_pages_without_gaps_or_overlap(client, db, owner):
    _seed(db, owner["uid"], 205)
    _, page1 = _get(client, owner, limit=100)
    oldest = min(o["createdAt"] for o in page1["data"])
    _, page2 = _get(client, owner, limit=100, before=oldest)
    oldest2 = min(o["createdAt"] for o in page2["data"])
    _, page3 = _get(client, owner, limit=100, before=oldest2)
    ids = _ids(page1) + _ids(page2) + _ids(page3)
    assert len(ids) == len(set(ids)) == 205
    assert page1["hasMore"] and page2["hasMore"] and page3["hasMore"] is False


def test_since_returns_only_changed_orders(client, db, owner, app, monkeypatch):
    uid = owner["uid"]
    _seed(db, uid, 50)
    monkeypatch.setattr("services.orders._now_ms", lambda: T0 + 10_000_000)
    _, first = _get(client, owner)
    cursor = first["cursor"]
    assert cursor == T0 + 10_000_000 - app._ORDERS_CURSOR_MARGIN_MS
    # طلب قديم يتبدّل حالته بعد التحميل
    monkeypatch.setattr("services.orders._now_ms", lambda: T0 + 10_000_500)
    r = client.post("/api/updateStatus", json={"orderId": f"ORD-{T0 + 3}", "status": "Refused"},
                    headers=owner["headers"])
    assert r.status_code == 200
    fakes.READS.clear()
    _, poll = _get(client, owner, since=cursor)
    assert _ids(poll) == [f"ORD-{T0 + 3}"] and poll["data"][0]["status"] == "Refused"
    assert _full_order_reads(uid) == []
    assert any(rd[0] == "query" and rd[2] == "updatedAt" for rd in fakes.READS)


def test_since_with_too_many_changes_asks_for_reset(client, db, owner, app, monkeypatch):
    monkeypatch.setattr(app, "_ORDERS_PAGE_MAX", 10)
    _seed(db, owner["uid"], 15)
    _, body = _get(client, owner, since=T0)
    assert body["reset"] is True and len(body["data"]) == 10


def test_created_after_for_the_chart(client, db, owner):
    _seed(db, owner["uid"], 20)
    _, body = _get(client, owner, createdAfter=T0 + 15_000)
    assert _ids(body) == [f"ORD-{T0 + i}" for i in range(19, 14, -1)]


@pytest.mark.parametrize("params", [{"limit": "x"}, {"since": "abc"}, {"before": "1.5e3"}])
def test_bad_paging_params_rejected(client, owner, params):
    code, _ = _get(client, owner, **params)
    assert code == 400


def test_query_failure_is_an_error_not_an_empty_list(client, owner, app, monkeypatch):
    monkeypatch.setattr(app, "_fb_query", lambda *a, **k: None)
    code, _ = _get(client, owner)
    assert code == 503


# ── الواجهة ─────────────────────────────────────────────
def _fn(name):
    start = INDEX.index(f"function {name}(")
    return INDEX[start:INDEX.index("\n}\n", start)]


def test_frontend_polls_only_changes_and_pauses_when_hidden():
    poll = _fn("pollOrders").replace(" ", "")
    assert "since:ORDERS_CURSOR" in poll and "document.hidden" in poll and "r.reset" in poll
    start = _fn("startOrdersPolling")
    assert "pollOrders" in start and "visibilitychange" in INDEX
    assert 'apiGet("/getOrders",{})' not in INDEX.replace(" ", "")


def test_logout_clears_cached_orders():
    out = _fn("logout").replace(" ", "")
    for reset in ("allOrders=[]", "ORDERS_BY_ID={}", "ORDERS_CURSOR=null"):
        assert reset in out


def test_frontend_load_older_and_chart_use_paging():
    assert "before:ORDERS_OLDEST" in _fn("loadOlderOrders").replace(" ", "")
    assert re.search(r'onclick="loadOlderOrders\(\)"', INDEX)
    assert "createdAfter:" in _fn("loadTrendChart").replace(" ", "")
    assert "limit:" in _fn("loadOrders").replace(" ", "")
