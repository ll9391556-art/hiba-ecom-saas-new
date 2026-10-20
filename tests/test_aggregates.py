# -*- coding: utf-8 -*-
"""Phase 3 / branch 5 — المجاميع الجارية (stats، customers، المخزون، التقييمات) لازم تساوي
الحساب الكامل بالضبط، والقراءات (لوحة، زبائن، متجر، منتجات) ما تنزّلش كل الطلبات."""
import pytest

from tests import fakes

ADMIN = {"X-Admin-Key": "dummy-admin-key"}


# ── مرجع: نفس منطق الكود القديم (قراءة كل الطلبات) ───────────
def legacy_dashboard(orders, products):
    tot = conf = ref = delivered = 0
    cents, sales = 0, {}
    for o in orders.values():
        tot += 1
        st = o.get("status", "")
        if st in ("Confirmed", "Delivered"):
            conf += 1
            cents += int(round(float(o.get("profit", 0)) * 100))
            sales[o.get("product", "")] = sales.get(o.get("product", ""), 0) + int(o.get("qty", 1))
            delivered += st == "Delivered"
        elif st == "Refused":
            ref += 1
            cents += int(round(float(o.get("profit", 0)) * 100))
    top = sorted([{"name": k, "qty": v} for k, v in sales.items() if v],
                 key=lambda x: (-x["qty"], x["name"]))[:5]
    low = []
    for p in products.values():
        rem = int(p.get("init", 0)) - sales.get(p.get("name", ""), 0)
        if rem <= 5:
            low.append({"name": p["name"], "rem": rem, "stat": "Out of Stock" if rem <= 0 else "Low Stock"})
    return {"totalOrders": tot, "confirmed": conf, "refused": ref, "delivered": delivered,
            "totalProfit": round(cents / 100, 2), "confirmRate": round(conf / tot * 100) if tot else 0,
            "refuseRate": round(ref / tot * 100) if tot else 0, "topProducts": top, "lowStock": low}


def legacy_customers(orders):
    import re
    cmap = {}
    for k, o in sorted(orders.items(), key=lambda kv: (kv[1].get("createdAt", 0), kv[0])):
        ph = re.sub(r"\D", "", str(o.get("phone") or ""))
        if not ph:
            continue
        c = cmap.setdefault(ph, {"name": o.get("name", ""), "phone": o.get("phone", ""), "city": o.get("city", ""),
                                 "totalOrders": 0, "stats": {"confirmed": 0, "refused": 0, "delivered": 0}})
        c["totalOrders"] += 1
        for st, field in (("Confirmed", "confirmed"), ("Refused", "refused"), ("Delivered", "delivered")):
            c["stats"][field] += o.get("status") == st
    return cmap


# ── سيناريو عبر المسارات الحقيقية ─────────────────────────
@pytest.fixture
def shop(db, seed_owner):
    owner = seed_owner()
    uid = owner["uid"]
    for name, init, sell, cost in (("Sac", 10, 1000, 600), ("Montre", 3, 2500.5, 1800.25), ("Robe", 6, 900, 500)):
        db.set(f"data/{uid}/products/{name}", {"name": name, "init": init, "sell": sell, "cost": cost})
    db.set(f"data/{uid}/cities/Alger", {"name": "Alger", "custShip": 400, "costShip": 300.5,
                                         "deskCust": 300, "deskCost": 200, "returnFee": 150.75})
    return owner


def _order(client, uid, phone, product, qty=1, name="Client"):
    r = client.post("/api/addOrder", json={"userId": uid, "data": {
        "name": name, "phone": phone, "city": "Alger", "product": product, "qty": qty}})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["orderId"]


def _status(client, owner, oid, status):
    assert client.post("/api/updateStatus", json={"orderId": oid, "status": status},
                       headers=owner["headers"]).status_code == 200


@pytest.fixture
def scenario(client, db, shop, app, monkeypatch):
    """طلبات بأرقام ومنتجات مختلفة، وتنقلات حالة فيها رجوع (Confirmed→Refused...)."""
    uid = shop["uid"]
    ticks = iter(range(1_700_000_000_000, 1_800_000_000_000, 1000))
    monkeypatch.setattr(app, "_now_ms", lambda: next(ticks))
    monkeypatch.setattr(app, "is_rate_limited", lambda *a, **k: False)
    a1 = _order(client, uid, "0555 11 11 11", "Sac", 2, "Amina")
    a2 = _order(client, uid, "0555111111", "Montre", 1, "Amina B")
    b1 = _order(client, uid, "0666222222", "Sac", 3, "Bilal")
    b2 = _order(client, uid, "0666-222-222", "Robe", 1, "Bilal")
    c1 = _order(client, uid, "0777333333", "Montre", 2, "Chahra")
    x1 = _order(client, uid, "0555444444", "Pro.duit/X", 1, "Odd")   # اسم منتج غير صالح كمفتاح
    _status(client, shop, a1, "Confirmed")
    _status(client, shop, a1, "Delivered")
    _status(client, shop, a2, "Confirmed")
    _status(client, shop, b1, "Confirmed")
    _status(client, shop, b1, "Refused")             # رجوع من Confirmed
    _status(client, shop, b2, "No Answer")
    _status(client, shop, c1, "Confirmed")
    _status(client, shop, x1, "Confirmed")
    assert client.post("/api/updateOrderDelivery", json={"orderId": c1, "deliveryType": "desk"},
                       headers=shop["headers"]).status_code == 200
    assert client.post("/api/submitRating", json={"userId": uid, "orderId": a1, "phone": "0555111111",
                                                  "rating": 4}).status_code == 200
    return {"uid": uid, "ids": dict(a1=a1, a2=a2, b1=b1, b2=b2, c1=c1, x1=x1)}


def _raw(db, uid):
    return db.get(f"data/{uid}/orders") or {}, db.get(f"data/{uid}/products") or {}, \
        db.get(f"data/{uid}/ratings") or {}


def test_running_stats_equal_full_recompute(app, db, scenario):
    uid = scenario["uid"]
    orders, _, ratings = _raw(db, uid)
    assert db.get(f"data/{uid}/stats") == app._compute_stats(orders, ratings)
    assert db.get(f"data/{uid}/customers") == app._compute_customers(orders)


def test_dashboard_matches_legacy_and_reads_no_orders(client, db, shop, scenario):
    uid = scenario["uid"]
    orders, products, _ = _raw(db, uid)
    fakes.READS.clear()
    d = client.get("/api/getDashboard", headers=shop["headers"]).get_json()["data"]
    assert d == legacy_dashboard(orders, products)
    assert {"name": "Pro.duit/X", "qty": 1} in d["topProducts"]
    assert ("get", f"/data/{uid}/orders", {}) not in fakes.READS


def test_customers_match_legacy_and_read_no_orders(client, db, shop, scenario):
    uid = scenario["uid"]
    orders, _, _ = _raw(db, uid)
    fakes.READS.clear()
    rows = client.get("/api/getCustomers", headers=shop["headers"]).get_json()["data"]
    assert ("get", f"/data/{uid}/orders", {}) not in fakes.READS
    expected = legacy_customers(orders)
    assert {r["phone"].replace(" ", "").replace("-", ""): {k: r[k] for k in ("name", "phone", "city", "totalOrders", "stats")}
            for r in rows} == {ph: c for ph, c in expected.items()}
    amina = next(r for r in rows if r["name"] == "Amina")
    assert amina["totalOrders"] == 2 and amina["stats"] == {"confirmed": 1, "refused": 0, "delivered": 1}


def test_stock_and_ratings_on_store_and_products(client, db, shop, scenario):
    uid = scenario["uid"]
    fakes.READS.clear()
    store = {p["name"]: p for p in client.get(f"/api/getStoreProducts?userId={uid}").get_json()["data"]}
    prods = {p["name"]: p for p in client.get("/api/getProducts", headers=shop["headers"]).get_json()["data"]}
    assert ("get", f"/data/{uid}/orders", {}) not in fakes.READS
    assert ("get", f"/data/{uid}/ratings", {}) not in fakes.READS
    # Sac: a1 (2, Delivered) — b1 رجع Refused فما يتحسبش
    assert store["Sac"]["sold"] == 2 and store["Sac"]["available"] == 8 and store["Sac"]["stat"] == "In Stock"
    # Montre: a2 (1) + c1 (2) = 3 من 3
    assert store["Montre"]["available"] == 0 and store["Montre"]["stat"] == "Out of Stock"
    assert store["Sac"]["avgRating"] == 4.0 and store["Sac"]["ratingCount"] == 1
    for name in ("Sac", "Montre", "Robe"):
        assert {k: prods[name][k] for k in ("sold", "available", "stat")} == \
               {k: store[name][k] for k in ("sold", "available", "stat")}


def test_store_cache_is_invalidated_by_order_changes(client, db, shop, scenario):
    uid = scenario["uid"]
    before = {p["name"]: p for p in client.get(f"/api/getStoreProducts?userId={uid}").get_json()["data"]}
    _status(client, shop, scenario["ids"]["b2"], "Confirmed")   # Robe +1
    after = {p["name"]: p for p in client.get(f"/api/getStoreProducts?userId={uid}").get_json()["data"]}
    assert after["Robe"]["sold"] == before["Robe"]["sold"] + 1


def test_delete_keeps_totals_exact(app, db, scenario):
    uid, oid = scenario["uid"], scenario["ids"]["a2"]
    order = db.get(f"data/{uid}/orders/{oid}")
    db.set(f"data/{uid}/orders/{oid}", None)
    app._apply_order_change(uid, order, None)
    orders, _, ratings = _raw(db, uid)
    assert db.get(f"data/{uid}/stats") == app._compute_stats(orders, ratings)
    assert db.get(f"data/{uid}/customers") == app._compute_customers(orders)


def test_bot_and_rating_paths_update_totals(app, db, shop, monkeypatch):
    uid = shop["uid"]
    bot_order = {"product": "Robe", "quantity": "2", "name": "Bot", "phone": "0888999999",
                 "city": "Alger", "delivery_type": "منزل", "address": "x"}
    assert app.save_order_from_bot(bot_order, {"User_ID": uid}, "SID1") is True
    orders, _, ratings = _raw(db, uid)
    assert db.get(f"data/{uid}/stats") == app._compute_stats(orders, ratings)
    assert db.get(f"data/{uid}/customers/0888999999")["totalOrders"] == 1


# ── recalc / backfill ────────────────────────────────────
def test_recalc_repairs_drift_and_is_rate_limited(client, app, db, shop, scenario, seed_member):
    uid = scenario["uid"]
    db.set(f"data/{uid}/stats/total", 999)
    db.set(f"data/{uid}/customers/0555111111/totalOrders", 42)
    r = client.post("/api/recalcStats", headers=shop["headers"])
    assert r.status_code == 200
    orders, _, ratings = _raw(db, uid)
    assert db.get(f"data/{uid}/stats") == app._compute_stats(orders, ratings)
    assert db.get(f"data/{uid}/customers") == app._compute_customers(orders)
    assert client.post("/api/recalcStats", headers=shop["headers"]).status_code == 429
    member = seed_member(shop, perms={"orders": True})
    assert client.post("/api/recalcStats", headers=member["headers"]).status_code == 403


def test_recalc_does_not_wipe_totals_when_read_fails(client, app, db, shop, scenario, monkeypatch):
    uid = scenario["uid"]
    stats = db.get(f"data/{uid}/stats")

    class UnavailableError(Exception):
        pass

    real_get = fakes.FakeReference.get
    monkeypatch.setattr(fakes.FakeReference, "get", lambda self, *a, **k: (_ for _ in ()).throw(UnavailableError())
                        if self.path.endswith("/orders") else real_get(self, *a, **k))
    monkeypatch.setattr(app, "sleep", lambda s: None)
    assert client.post("/api/recalcStats", headers=shop["headers"]).status_code == 503
    assert db.get(f"data/{uid}/stats") == stats


def test_admin_backfill_builds_aggregates_for_legacy_data(client, app, db, seed_owner):
    owner = seed_owner()
    uid = owner["uid"]
    db.set(f"data/{uid}/products/Sac", {"name": "Sac", "init": 5})
    db.set(f"data/{uid}/orders", {
        "ORD-1690000000000": {"id": "ORD-1690000000000", "phone": "0555", "product": "Sac", "qty": 2,
                              "status": "Delivered", "profit": 800.5, "name": "A"},
        "ORD-1690000001000": {"id": "ORD-1690000001000", "phone": "0555", "product": "Sac", "qty": 1,
                              "status": "Refused", "profit": -150, "name": "A"}})
    db.set(f"data/{uid}/ratings/Sac", {"-r1": {"rating": 5}, "-r2": {"rating": 2}})
    res = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["aggregates"]
    assert res == {"merchants": 1, "failed": []}
    orders, _, ratings = _raw(db, uid)
    assert db.get(f"data/{uid}/stats") == app._compute_stats(orders, ratings)
    d = client.get("/api/getDashboard", headers=owner["headers"]).get_json()["data"]
    assert d["totalProfit"] == 650.5 and d["delivered"] == 1 and d["refused"] == 1
    store = client.get(f"/api/getStoreProducts?userId={uid}").get_json()["data"]
    assert store[0]["avgRating"] == 3.5 and store[0]["available"] == 3


# ── /api/saas ما يقدرش يكتب المجاميع ولا الطلبات ───────────
@pytest.mark.parametrize("path", ["data/{uid}/stats", "data/{uid}//stats/total", "data/{uid}/orders/x",
                                  "data/{uid}/customers", "data/{uid}", "data/{uid}/"])
def test_api_saas_cannot_write_aggregates(client, shop, path):
    r = client.post("/api/saas", headers=shop["headers"],
                    json={"action": "firebaseSet", "path": path.format(uid=shop["uid"]), "payload": {"x": 1}})
    assert r.status_code == 403
