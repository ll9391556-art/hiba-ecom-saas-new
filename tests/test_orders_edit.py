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


# ── 3. الحذف ─────────────────────────────────────────────
def _delete(client, headers, oid):
    return client.post("/api/deleteOrder", json={"orderId": oid}, headers=headers)


@pytest.mark.parametrize("status", ["Confirmed", "Delivered", "Refused", "Pending"])
def test_delete_keeps_totals_exact(client, app, db, shop, status):
    uid = shop["uid"]
    keep = _order(client, uid, phone="0666222222", qty=1, name="Bilal")
    _status(client, shop, keep, "Confirmed")
    oid = _order(client, uid, phone="0555111111", qty=3)
    if status != "Pending":
        _status(client, shop, oid, status)
    r = _delete(client, shop["headers"], oid)
    assert r.status_code == 200, r.get_json()
    assert db.get(f"data/{uid}/orders/{oid}") is None
    _assert_exact(app, db, uid)
    stats = db.get(f"data/{uid}/stats")
    assert stats["total"] == 1 and stats["confirmed"] == 1 and stats["refused"] == 0
    assert db.get(f"data/{uid}/stats/sales/Sac/qty") == 1                 # المخزون رجع
    assert set(db.get(f"data/{uid}/customers")) == {"0666222222"}
    tomb = db.get(f"data/{uid}/deletedOrders/{oid}")
    assert tomb["by"] == "owner" and isinstance(tomb["at"], int)


def test_delete_twice_changes_nothing_the_second_time(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    _status(client, shop, oid, "Delivered")
    assert _delete(client, shop["headers"], oid).status_code == 200
    stats = db.get(f"data/{uid}/stats")
    assert _delete(client, shop["headers"], oid).status_code == 404
    assert db.get(f"data/{uid}/stats") == stats
    assert len([e for e in _audit(db, uid) if e["action"] == "حذف طلب"]) == 1
    _assert_exact(app, db, uid)


def test_concurrent_delete_loses_the_claim(client, app, db, shop):
    """طلب حذف آخر حجز الطلبية (deleting حديث) → هذا يرجع 404 والمجاميع ما تتلمسش."""
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    import services.orders as so
    db.set(f"data/{uid}/orders/{oid}/deleting", so._now_ms())
    stats = db.get(f"data/{uid}/stats")
    assert _delete(client, shop["headers"], oid).status_code == 404
    assert _edit(client, shop["headers"], oid, qty=2).status_code == 404   # ما يتعدّلش وسط الحذف
    assert db.get(f"data/{uid}/stats") == stats


def test_stale_claim_from_a_failed_delete_does_not_block(client, app, db, shop):
    import services.orders as so
    uid = shop["uid"]
    oid = _order(client, uid)
    db.set(f"data/{uid}/orders/{oid}/deleting", so._now_ms() - so._DELETE_CLAIM_MS - 1)
    assert _edit(client, shop["headers"], oid, name="B").status_code == 200
    assert "deleting" not in db.get(f"data/{uid}/orders/{oid}")
    db.set(f"data/{uid}/orders/{oid}/deleting", so._now_ms() - so._DELETE_CLAIM_MS - 1)
    assert _delete(client, shop["headers"], oid).status_code == 200
    _assert_exact(app, db, uid)


def test_failed_delete_rolls_back(client, app, db, shop, monkeypatch):
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    monkeypatch.setattr("services.orders._fb_delete", lambda path: False)
    assert _delete(client, shop["headers"], oid).status_code == 503
    assert db.get(f"data/{uid}/orders/{oid}") == before                    # بلا deleting
    assert db.get(f"data/{uid}/stats") == stats
    assert db.get(f"data/{uid}/deletedOrders/{oid}") is None


def test_delete_is_owner_only(client, app, db, shop, seed_member):
    """الحذف للمالك برك: عضو عندو orders يعدّل، لكن ما يحذفش (403)."""
    uid = shop["uid"]
    oid = _order(client, uid)
    member = seed_member(shop, "m_orders", perms={"orders": True})
    assert _delete(client, member["headers"], oid).status_code == 403
    assert db.get(f"data/{uid}/orders/{oid}") is not None
    assert _edit(client, member["headers"], oid, name="Edited").status_code == 200


def test_delete_is_audited(client, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2, name="Amina")
    assert _delete(client, shop["headers"], oid).status_code == 200
    (entry,) = _audit(db, uid)
    assert entry["action"] == "حذف طلب" and entry["actor"] == "owner"
    for part in (oid, "Amina", "0555111111", "Sac×2", "Pending"):
        assert part in entry["details"], part


def test_other_merchant_cannot_delete(client, app, db, shop, seed_owner):
    uid = shop["uid"]
    oid = _order(client, uid)
    before = db.get(f"data/{uid}/orders/{oid}")
    other = seed_owner(username="owner2", uid="2002")
    assert _delete(client, other["headers"], oid).status_code == 404
    assert db.get(f"data/{uid}/orders/{oid}") == before
    assert db.get("data/2002/deletedOrders") is None


@pytest.mark.parametrize("oid", ["ORD-1/x", "ORD.1", "", None])
def test_delete_bad_order_id(client, shop, oid):
    assert _delete(client, shop["headers"], oid).status_code == 400


def test_deleted_woo_order_is_not_reimported(client, db, shop, monkeypatch):
    uid = shop["uid"]
    db.set(f"data/{uid}/integrations/woocommerce", {"connected": True, "storeUrl": "https://shop.test",
                                                     "consumerKeyEnc": "x", "consumerSecretEnc": "y"})
    monkeypatch.setattr("routes.integrations._validate_and_pin_store_url", lambda url: ("shop.test", "203.0.113.5"))
    monkeypatch.setattr("routes.integrations._decrypt_secret", lambda tok: "dummy-secret")

    class Resp:
        ok, status_code = True, 200

        def json(self):
            return [{"id": 5, "billing": {"phone": "0555111111"}, "line_items": []}]
    monkeypatch.setattr("routes.integrations._request_with_pinned_dns", lambda *a, **k: Resp())
    assert client.post("/api/woo/sync", headers=shop["headers"]).get_json()["data"]["imported"] == 1
    assert _delete(client, shop["headers"], "ORD-WOO-5").status_code == 200
    assert client.post("/api/woo/sync", headers=shop["headers"]).get_json()["data"]["imported"] == 0
    assert db.get(f"data/{uid}/orders/ORD-WOO-5") is None


def test_polling_reports_deleted_ids(client, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    cursor = client.get("/api/getOrders", headers=shop["headers"]).get_json()["cursor"]
    assert _delete(client, shop["headers"], oid).status_code == 200
    body = client.get(f"/api/getOrders?since={cursor}", headers=shop["headers"]).get_json()
    assert body["deleted"] == [oid]
    assert client.get("/api/getOrders", headers=shop["headers"]).get_json().get("deleted") is None


def test_api_saas_cannot_write_tombstones(client, shop):
    r = client.post("/api/saas", headers=shop["headers"], json={
        "action": "firebaseSet", "path": f"data/{shop['uid']}/deletedOrders/ORD-1", "payload": {"x": 1}})
    assert r.status_code == 403


# ── 4. تعديل منتج ────────────────────────────────────────
def _update_product(client, headers, **data):
    return client.post("/api/updateProduct", json={"data": data}, headers=headers)


def _stock(client, headers):
    return {p["name"]: p for p in client.get("/api/getProducts", headers=headers).get_json()["data"]}


def test_update_product_changes_allowed_fields_only(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    _status(client, shop, oid, "Confirmed")
    order_before = db.get(f"data/{uid}/orders/{oid}")
    r = _update_product(client, shop["headers"], name="Sac", sell=1200, cost=700, init=20, category="Cuir",
                        visible="no", sold=999, available=999, created_at=1, stat="Out of Stock")
    assert r.status_code == 200, r.get_json()
    p = db.get(f"data/{uid}/products/Sac")
    assert (p["sell"], p["cost"], p["init"], p["category"], p["visible"]) == (1200, 700, 20, "Cuir", "no")
    for k in ("sold", "available", "created_at", "stat"):
        assert k not in p, k
    assert _stock(client, shop["headers"])["Sac"]["available"] == 18           # init − ventes
    assert db.get(f"data/{uid}/orders/{oid}") == order_before                  # الطلبيات القديمة بسعرها
    _assert_exact(app, db, uid)
    (entry,) = [e for e in _audit(db, uid) if e["action"] == "تعديل منتج"]
    assert "sell: 1000 → 1200" in entry["details"] and "init: 10 → 20" in entry["details"]


def test_update_product_invalidates_store_cache(client, app, db, shop):
    uid = shop["uid"]
    app._store_products_cache[uid] = ("cached", 10**12)
    assert _update_product(client, shop["headers"], name="Sac", sell=1500).status_code == 200
    assert uid not in app._store_products_cache


def test_update_unknown_product_is_404_and_creates_nothing(client, db, shop):
    assert _update_product(client, shop["headers"], name="Nouveau", sell=10).status_code == 404
    assert db.get(f"data/{shop['uid']}/products/Nouveau") is None


@pytest.mark.parametrize("data", [
    {"sell": -1}, {"cost": "x"}, {"init": 1.5}, {"init": -2}, {"visible": "maybe"},
    {"image": "javascript:alert(1)"}, {"images": "not-a-list"}, {"images": ["ftp://x"]},
    {"category": "x" * 201}, {"description": "x" * 5001},
])
def test_update_product_rejects_bad_values(client, db, shop, data):
    before = db.get(f"data/{shop['uid']}/products/Sac")
    assert _update_product(client, shop["headers"], name="Sac", **data).status_code == 400
    assert db.get(f"data/{shop['uid']}/products/Sac") == before


def test_update_product_isolation_and_permissions(client, db, shop, seed_owner, seed_member):
    uid = shop["uid"]
    before = db.get(f"data/{uid}/products/Sac")
    other = seed_owner(username="owner2", uid="2002")
    assert _update_product(client, other["headers"], name="Sac", sell=1).status_code == 404
    assert db.get(f"data/{uid}/products/Sac") == before and db.get("data/2002/products") is None
    no = seed_member(shop, "m_orders", perms={"orders": True})
    assert _update_product(client, no["headers"], name="Sac", sell=1).status_code == 403
    yes = seed_member(shop, "m_products", perms={"products": True})
    assert _update_product(client, yes["headers"], name="Sac", sell=1100).status_code == 200
    assert [e["actor"] for e in _audit(db, uid)] == ["m_products"]
