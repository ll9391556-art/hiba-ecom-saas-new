# -*- coding: utf-8 -*-
"""المهمة 3: تعديل وحذف الطلبيات وتعديل المنتجات. بعد كل عملية، المجاميع الجارية (stats/customers)
لازم تساوي الحساب الكامل بالضبط، بلا ما يتحسب الفرق مرتين، وكل تاجر يلمس غير بياناتو."""
import pytest

from tests import fakes


@pytest.fixture
def shop(db, seed_owner, app, monkeypatch):
    owner = seed_owner()
    uid = owner["uid"]
    for name, init, sell, cost in (("Sac", 10, 1000, 600), ("Montre", 3, 2500.5, 1800.25)):
        db.set(f"data/{uid}/products/{name}", {"name": name, "init": init, "sell": sell, "cost": cost})
    db.set(f"data/{uid}/cities/Alger", {"name": "Alger", "custShip": 400, "costShip": 300.5,
                                         "deskCust": 300, "deskCost": 200, "returnFee": 150.75})
    db.set(f"data/{uid}/cities/Oran", {"name": "Oran", "custShip": 600, "costShip": 500,
                                        "deskCust": 450, "deskCost": 350, "returnFee": 200})
    ticks = iter(range(1_700_000_000_000, 1_800_000_000_000, 1000))
    monkeypatch.setattr("services.orders._now_ms", lambda: next(ticks))
    monkeypatch.setattr(app, "is_rate_limited", lambda *a, **k: False)
    return owner


def _order(client, uid, phone="0555111111", product="Sac", qty=1, name="Amina", city="Alger"):
    r = client.post("/api/addOrder", json={"userId": uid, "data": {
        "name": name, "phone": phone, "city": city, "product": product, "qty": qty}})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["orderId"]


def _status(client, owner, oid, status):
    r = client.post("/api/updateStatus", json={"orderId": oid, "status": status}, headers=owner["headers"])
    assert r.status_code == 200, r.get_json()


def _edit(client, headers, oid, **data):
    return client.post("/api/editOrder", json={"orderId": oid, "data": data}, headers=headers)


def _assert_exact(app, db, uid):
    orders = db.get(f"data/{uid}/orders") or {}
    ratings = db.get(f"data/{uid}/ratings") or {}
    assert (db.get(f"data/{uid}/stats") or {}) == app._compute_stats(orders, ratings)
    assert (db.get(f"data/{uid}/customers") or {}) == app._compute_customers(orders)


def _audit(db, uid):
    return list((db.get(f"data/{uid}/auditLog") or {}).values())


# ── 1. تعديل المجموع ──────────────────────────────────────
def test_manual_total_sets_profit_from_total(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    _status(client, shop, oid, "Confirmed")
    r = _edit(client, shop["headers"], oid, total=2000)
    assert r.status_code == 200, r.get_json()
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["total"] == 2000
    assert o["profit"] == pytest.approx(2000 - 600 * 2 - 300.5)   # total − cost×qty − ship_cost
    assert r.get_json()["data"]["total"] == 2000
    _assert_exact(app, db, uid)
    assert db.get(f"data/{uid}/stats")["profitCents"] == round((2000 - 1200 - 300.5) * 100)


def test_qty_and_product_change_move_sales_and_recompute_total(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    _status(client, shop, oid, "Confirmed")
    assert _edit(client, shop["headers"], oid, product="Montre", qty=3, deliveryType="desk").status_code == 200
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["total"] == pytest.approx(2500.5 * 3 + 300)
    assert o["profit"] == pytest.approx((2500.5 - 1800.25) * 3 + (300 - 200))
    _assert_exact(app, db, uid)
    sales = {e["name"]: e["qty"] for e in db.get(f"data/{uid}/stats/sales").values()}
    assert sales == {"Montre": 3}
    stock = {p["name"]: p["available"] for p in client.get("/api/getProducts", headers=shop["headers"]).get_json()["data"]}
    assert stock == {"Sac": 10, "Montre": 0}


def test_name_only_edit_keeps_total_and_profit(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    before = db.get(f"data/{uid}/orders/{oid}")
    db.set(f"data/{uid}/products/Sac/sell", 5000)            # السعر تبدّل من بعد الطلب
    assert _edit(client, shop["headers"], oid, name="Amina K").status_code == 200
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["name"] == "Amina K" and o["total"] == before["total"] and o["profit"] == before["profit"]
    _assert_exact(app, db, uid)


def test_phone_change_moves_the_customer(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, phone="0555111111")
    assert _edit(client, shop["headers"], oid, phone="0666 22 22 22").status_code == 200
    assert db.get(f"data/{uid}/orders/{oid}/phoneDigits") == "0666222222"
    assert set(db.get(f"data/{uid}/customers")) == {"0666222222"}
    _assert_exact(app, db, uid)


# ── 2. تعديل الحالة مع تعديل ─────────────────────────────
def test_status_and_qty_in_one_edit_count_once(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=1)
    assert _edit(client, shop["headers"], oid, status="Confirmed", qty=4).status_code == 200
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["status"] == "Confirmed" and o["date_sent"]
    assert o["profit"] == pytest.approx((1000 - 600) * 4 + (400 - 300.5))
    stats = db.get(f"data/{uid}/stats")
    assert stats["confirmed"] == 1 and stats["total"] == 1
    assert db.get(f"data/{uid}/stats/sales/Sac/qty") == 4
    _assert_exact(app, db, uid)
    _status(client, shop, oid, "Refused")
    assert _edit(client, shop["headers"], oid, city="Oran").status_code == 200
    assert db.get(f"data/{uid}/orders/{oid}/profit") == -200
    stats = db.get(f"data/{uid}/stats")
    assert stats["confirmed"] == 0 and stats["refused"] == 1 and "sales" not in stats
    _assert_exact(app, db, uid)


def test_back_to_pending_zeroes_profit(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Delivered")
    assert _edit(client, shop["headers"], oid, status="Pending").status_code == 200
    assert db.get(f"data/{uid}/orders/{oid}/profit") == 0
    _assert_exact(app, db, uid)


# ── السباق: before يتقرا داخل الـ transaction ─────────────
def test_concurrent_change_is_not_counted_twice(client, app, db, shop, monkeypatch):
    """أول محاولة تشوف قيمة قديمة (طلب آخر بدّل الحالة في نفس الوقت)، وFirebase يعاود ينادي
    الدالة بالقيمة الحالية. الفرق لازم يتحسب من القيمة الحقيقية، مرة وحدة."""
    uid = shop["uid"]
    oid = _order(client, uid, qty=1)
    stale = db.get(f"data/{uid}/orders/{oid}")
    _status(client, shop, oid, "Confirmed")                  # الطلب الآخر نجح قبلنا
    real = fakes.FakeReference.transaction

    def racing(self, fn):
        if self.path.endswith(f"/orders/{oid}"):
            fn(dict(stale))                                  # المحاولة الأولى: ترفض (تعارض)
        return real(self, fn)
    monkeypatch.setattr(fakes.FakeReference, "transaction", racing)
    assert _edit(client, shop["headers"], oid, qty=3).status_code == 200
    assert db.get(f"data/{uid}/stats/sales/Sac/qty") == 3
    _assert_exact(app, db, uid)


def test_noop_edit_writes_nothing(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    before = db.get(f"data/{uid}/orders/{oid}")
    r = _edit(client, shop["headers"], oid, name="Amina", qty=1)
    assert r.status_code == 200
    assert db.get(f"data/{uid}/orders/{oid}") == before
    assert _audit(db, uid) == []


# ── الفحص ────────────────────────────────────────────────
@pytest.mark.parametrize("oid", ["ORD-1/x", "ORD.1", "", "a" * 81, "ORD-1#"])
def test_bad_order_id_is_rejected(client, db, shop, oid):
    assert _edit(client, shop["headers"], oid, name="X").status_code == 400


@pytest.mark.parametrize("data", [
    {"qty": 0}, {"qty": "abc"}, {"qty": 1000}, {"total": -1}, {"total": "x"}, {"status": "Lost"},
    {"deliveryType": "air"}, {"name": ""}, {"name": "x" * 101}, {"phone": "12"},
    {"product": "Inconnu"}, {"city": "Atlantis"},
])
def test_invalid_fields_are_rejected(client, db, shop, data):
    uid = shop["uid"]
    oid = _order(client, uid)
    before = db.get(f"data/{uid}/orders/{oid}")
    assert _edit(client, shop["headers"], oid, **data).status_code == 400
    assert db.get(f"data/{uid}/orders/{oid}") == before


def test_protected_fields_are_ignored(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    before = db.get(f"data/{uid}/orders/{oid}")
    assert _edit(client, shop["headers"], oid, name="Z", profit=99999, id="ORD-X", createdAt=1,
                 source="bot", couponCode="FREE", discountApplied=500).status_code == 200
    o = db.get(f"data/{uid}/orders/{oid}")
    for k in ("profit", "id", "createdAt", "source"):
        assert o.get(k) == before.get(k), k
    assert "couponCode" not in o and "discountApplied" not in o
    _assert_exact(app, db, uid)


def test_legacy_free_text_product_can_still_be_edited(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, product="Ancien produit")
    assert _edit(client, shop["headers"], oid, product="Ancien produit", name="B").status_code == 200
    _assert_exact(app, db, uid)


def test_unknown_order_is_404(client, shop):
    assert _edit(client, shop["headers"], "ORD-404", name="X").status_code == 404


# ── العزل والصلاحيات والـ audit ───────────────────────────
def test_other_merchant_cannot_edit(client, app, db, shop, seed_owner):
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    other = seed_owner(username="owner2", uid="2002")
    assert _edit(client, other["headers"], oid, qty=5, name="Hack").status_code == 404
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get(f"data/{uid}/stats") == stats
    assert db.get("data/2002/orders") is None


def test_member_needs_orders_permission_to_edit(client, db, shop, seed_member):
    uid = shop["uid"]
    oid = _order(client, uid)
    no = seed_member(shop, "m_no", perms={"products": True})
    assert _edit(client, no["headers"], oid, name="X").status_code == 403
    yes = seed_member(shop, "m_yes", perms={"orders": True})
    assert _edit(client, yes["headers"], oid, name="Y").status_code == 200
    log = _audit(db, uid)
    assert len(log) == 1 and log[0]["actor"] == "m_yes" and log[0]["action"] == "تعديل طلب"


def test_edit_is_audited_with_the_diff(client, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=1)
    assert _edit(client, shop["headers"], oid, qty=2, status="Confirmed").status_code == 200
    (entry,) = _audit(db, uid)
    assert entry["actor"] == "owner" and oid in entry["details"]
    assert "qty: 1 → 2" in entry["details"] and "status: Pending → Confirmed" in entry["details"]
