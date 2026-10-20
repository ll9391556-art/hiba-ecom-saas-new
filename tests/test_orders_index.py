# -*- coding: utf-8 -*-
"""Phase 3 / branch 2 — كل كتابة طلب تضيف createdAt/updatedAt/phoneDigits (المفهرسة فـ
database.rules.json)، trackOrder يستعمل الفهرس بلا تنزيل كل الطلبات، وتعبئة الطلبات القديمة."""
import itertools
import pathlib
import re

import pytest

from tests import fakes

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADMIN = {"X-Admin-Key": "dummy-admin-key"}


@pytest.fixture
def clock(app, monkeypatch):
    """_now_ms يزيد بـ 1000 فكل نداء — باش نفرّقو createdAt على updatedAt."""
    ticks = itertools.count(1_700_000_000_000, 1000)
    monkeypatch.setattr(app, "_now_ms", lambda: next(ticks))


@pytest.fixture
def store(db, seed_owner):
    owner = seed_owner()
    uid = owner["uid"]
    db.set(f"data/{uid}/products/Sac", {"name": "Sac", "sell": 1000, "cost": 600, "init": 10})
    db.set(f"data/{uid}/cities/Alger", {"name": "Alger", "custShip": 400, "costShip": 300,
                                         "deskCust": 300, "deskCost": 200})
    return owner


def _orders(db, uid):
    return db.get(f"data/{uid}/orders") or {}


def _assert_fields(order, phone_digits):
    assert isinstance(order["createdAt"], int) and isinstance(order["updatedAt"], int)
    assert order["phoneDigits"] == phone_digits


def _add_public_order(client, uid, phone="0555 12-34-56"):
    r = client.post("/api/addOrder", json={"userId": uid, "data": {
        "name": "Amina", "phone": phone, "city": "Alger", "product": "Sac", "qty": 1}})
    assert r.status_code == 200
    return r.get_json()["data"]["orderId"]


# ── كل مسار كتابة يضبط الحقول ────────────────────────────
def test_public_add_order_sets_index_fields(client, db, store, clock):
    oid = _add_public_order(client, store["uid"])
    _assert_fields(_orders(db, store["uid"])[oid], "0555123456")


def test_status_and_delivery_updates_keep_created_and_bump_updated(client, db, store, clock):
    uid, h = store["uid"], store["headers"]
    oid = _add_public_order(client, uid)
    first = _orders(db, uid)[oid]
    assert client.post("/api/updateStatus", json={"orderId": oid, "status": "Confirmed"}, headers=h).status_code == 200
    after_status = _orders(db, uid)[oid]
    assert after_status["createdAt"] == first["createdAt"] and after_status["updatedAt"] > first["updatedAt"]
    assert client.post("/api/updateOrderDelivery", json={"orderId": oid, "deliveryType": "desk"},
                       headers=h).status_code == 200
    after_delivery = _orders(db, uid)[oid]
    assert after_delivery["createdAt"] == first["createdAt"]
    assert after_delivery["updatedAt"] > after_status["updatedAt"]
    _assert_fields(after_delivery, "0555123456")


def test_bot_order_sets_index_fields(app, db, store, clock):
    order = {"product": "Sac", "quantity": "1", "name": "Amina", "phone": "+213 555-12-34-56",
             "city": "Alger", "delivery_type": "منزل", "address": "12 Rue"}
    assert app.save_order_from_bot(order, {"User_ID": store["uid"]}, "SID1") is True
    (saved,) = _orders(db, store["uid"]).values()
    _assert_fields(saved, "213555123456")


def test_rating_patch_bumps_updated_at(client, db, store, clock):
    uid = store["uid"]
    oid = _add_public_order(client, uid)
    db.set(f"data/{uid}/orders/{oid}/status", "Delivered")
    before = _orders(db, uid)[oid]["updatedAt"]
    r = client.post("/api/submitRating", json={"userId": uid, "orderId": oid, "phone": "0555123456",
                                               "rating": 5})
    assert r.status_code == 200
    assert _orders(db, uid)[oid]["updatedAt"] > before


def test_woo_sync_dedupes_by_key_without_reading_all_orders(client, db, store, app, monkeypatch, clock):
    uid = store["uid"]
    db.set(f"data/{uid}/integrations/woocommerce", {"connected": True, "storeUrl": "https://shop.test",
                                                     "consumerKeyEnc": "x", "consumerSecretEnc": "y"})
    db.set(f"data/{uid}/orders/ORD-WOO-1", {"id": "ORD-WOO-1", "wooOrderId": "1", "phone": "0555"})
    monkeypatch.setattr(app, "_validate_and_pin_store_url", lambda url: ("shop.test", "203.0.113.5"))
    monkeypatch.setattr(app, "_decrypt_secret", lambda tok: "dummy-secret")

    class Resp:
        ok, status_code = True, 200

        def json(self):
            return [{"id": 1, "billing": {"phone": "0555"}, "line_items": []},
                    {"id": 2, "billing": {"phone": "0666 77 88", "first_name": "B"},
                     "line_items": [{"name": "Sac", "quantity": 2}], "total": "2400"}]

    monkeypatch.setattr(app, "_request_with_pinned_dns", lambda *a, **k: Resp())
    fakes.READS.clear()
    r = client.post("/api/woo/sync", headers=store["headers"])
    assert r.get_json()["data"]["imported"] == 1
    orders = _orders(db, uid)
    assert set(orders) == {"ORD-WOO-1", "ORD-WOO-2"}
    _assert_fields(orders["ORD-WOO-2"], "06667788")
    assert ("get", f"/data/{uid}/orders", {}) not in fakes.READS
    assert ("get", f"/data/{uid}/orders", {"shallow": True}) in fakes.READS


def test_no_raw_order_writes_left():
    """كل كتابة طلب تمر من _save_order/_patch_order — وإلا الحقول المفهرسة تتنسى."""
    raw = re.compile(r"_fb_(put|patch)\(f\"data/\{uid\}/orders/")
    hits = []
    for p in [ROOT / "app.py", *sorted((ROOT / "features").glob("*.py"))]:
        current_def = ""
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = re.match(r"def (\w+)\(", line)
            if m:
                current_def = m.group(1)
            if raw.search(line) and current_def not in ("_save_order", "_patch_order"):
                hits.append(f"{p.name}:{i}")
    assert hits == []


# ── trackOrder بالفهرس ─────────────────────────────────
def test_track_order_uses_index_not_full_read(client, db, store, clock):
    uid = store["uid"]
    mine = _add_public_order(client, uid, "0555 12 34 56")
    _add_public_order(client, uid, "0666000000")
    fakes.READS.clear()
    r = client.get(f"/api/trackOrder?userId={uid}&phone=0555-123-456")
    data = r.get_json()["data"]
    assert [o["id"] for o in data] == [mine]
    assert ("get", f"/data/{uid}/orders", {}) not in fakes.READS
    assert any(rd[0] == "query" and rd[2] == "phoneDigits" and rd[3]["equal_to"] == "0555123456"
               for rd in fakes.READS)


def test_track_order_reports_failure_instead_of_empty(client, app, store, monkeypatch):
    monkeypatch.setattr(app, "_fb_query", lambda *a, **k: None)
    r = client.get(f"/api/trackOrder?userId={store['uid']}&phone=0555123456")
    assert r.status_code == 503


# ── تعبئة الطلبات القديمة ─────────────────────────────────
LEGACY = {
    "ORD-1690000000000": {"id": "ORD-1690000000000", "phone": "0555 12 34 56", "status": "Pending",
                          "date": "2023-07-22 04:26"},
    "ORD-WOO-77": {"id": "ORD-WOO-77", "phone": "0666", "date": "2023-01-02 03:04"},
    "ORD-ODD": {"id": "ORD-ODD", "phone": ""},
}


def test_backfill_requires_admin_key(client):
    assert client.post("/api/admin/rebuildIndexes").status_code == 403


def test_backfill_fills_legacy_orders_and_is_idempotent(client, db, store, app, clock):
    uid = store["uid"]
    db.set(f"data/{uid}/orders", LEGACY)
    db.set("data/2002/orders/ORD-1700000000000", {"id": "ORD-1700000000000", "phone": "0777"})
    assert client.get(f"/api/trackOrder?userId={uid}&phone=0555123456").get_json()["data"] == []

    r = client.post("/api/admin/rebuildIndexes", headers=ADMIN)
    assert r.status_code == 200
    res = r.get_json()["data"]["orders"]
    assert res == {"merchants": 2, "checked": 4, "updated": 4}

    orders = _orders(db, uid)
    assert orders["ORD-1690000000000"]["createdAt"] == 1690000000000           # من المعرّف
    assert orders["ORD-WOO-77"]["createdAt"] == app._order_created_ms("ORD-WOO-77", LEGACY["ORD-WOO-77"])
    assert orders["ORD-WOO-77"]["createdAt"] < 1_700_000_000_000                # من حقل date، ماشي دابا
    assert orders["ORD-ODD"]["phoneDigits"] == ""
    assert orders["ORD-1690000000000"]["status"] == "Pending"                   # باقي الحقول ما تتمسّش
    _assert_fields(orders["ORD-1690000000000"], "0555123456")
    assert [o["id"] for o in client.get(f"/api/trackOrder?userId={uid}&phone=0555123456").get_json()["data"]] \
        == ["ORD-1690000000000"]

    again = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["orders"]
    assert again == {"merchants": 2, "checked": 4, "updated": 0}
