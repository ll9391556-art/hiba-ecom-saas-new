# -*- coding: utf-8 -*-
"""المهمة 3.1: updateStatus وupdateOrderDelivery فـ transaction على الطلبية (_mutate_order).
طلبين فنفس الوقت ياخذو نفس before → الفرق لازم يتحسب مرة وحدة، والمجاميع = الحساب الكامل.
وللتاجر نفس السلوك: نفس الردود، نفس التواريخ (date_sent/date_delivered)، نفس حساب الربح."""
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


def _set_status(client, headers, oid, status):
    return client.post("/api/updateStatus", json={"orderId": oid, "status": status}, headers=headers)


def _status(client, owner, oid, status):
    r = _set_status(client, owner["headers"], oid, status)
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {"status": "ok", "data": True}


def _assert_exact(app, db, uid):
    orders = db.get(f"data/{uid}/orders") or {}
    ratings = db.get(f"data/{uid}/ratings") or {}
    assert (db.get(f"data/{uid}/stats") or {}) == app._compute_stats(orders, ratings)
    assert (db.get(f"data/{uid}/customers") or {}) == app._compute_customers(orders)


def _audit(db, uid):
    return list((db.get(f"data/{uid}/auditLog") or {}).values())


def _stale_reads(monkeypatch, oid, stale, times=None):
    """_fb_get (في routes.orders) يرجّع النسخة القديمة تاع الطلبية: كأنو طلب آخر كتب من بعد قرايتنا.
    times=None: ديما، وإلا غير أول `times` قراءات."""
    import routes.orders as ro
    real, left = ro._fb_get, [times]

    def get(path, *a, **k):
        if path.endswith(f"/orders/{oid}") and (left[0] is None or left[0] > 0):
            if left[0] is not None:
                left[0] -= 1
            return dict(stale)
        return real(path, *a, **k)
    monkeypatch.setattr("routes.orders._fb_get", get)


def _fail_order_txn(monkeypatch, oid):
    real = fakes.FakeReference.transaction

    def broken(self, fn):
        if self.path.endswith(f"/orders/{oid}"):
            raise ConnectionError("firebase down")
        return real(self, fn)
    monkeypatch.setattr(fakes.FakeReference, "transaction", broken)


# ── updateStatus: نفس السلوك ─────────────────────────────
def test_status_profit_and_dates_are_unchanged(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    path = f"data/{uid}/orders/{oid}"
    _status(client, shop, oid, "Confirmed")
    o = db.get(path)
    assert o["profit"] == pytest.approx((1000 - 600) * 2 + (400 - 300.5)) and o["date_sent"]
    assert not o.get("date_delivered")
    db.set(f"{path}/date_sent", "2020-01-01 10:00")
    _status(client, shop, oid, "Delivered")
    o = db.get(path)
    assert o["date_sent"] == "2020-01-01 10:00" and o["date_delivered"]
    assert o["profit"] == pytest.approx(899.5)
    db.set(f"{path}/date_delivered", "2020-01-02 10:00")
    _status(client, shop, oid, "Confirmed")
    _status(client, shop, oid, "Delivered")
    o = db.get(path)
    assert o["date_sent"] == "2020-01-01 10:00" and o["date_delivered"] == "2020-01-02 10:00"
    _status(client, shop, oid, "Refused")
    assert db.get(f"{path}/profit") == -150.75
    _assert_exact(app, db, uid)
    for st in ("Pending", "No Answer"):
        _status(client, shop, oid, st)
        assert db.get(f"{path}/profit") == 0
        _assert_exact(app, db, uid)


def test_status_with_missing_product_sets_profit_zero(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    db.set(f"data/{uid}/products/Sac", None)
    _status(client, shop, oid, "Confirmed")
    assert db.get(f"data/{uid}/orders/{oid}/profit") == 0
    _assert_exact(app, db, uid)


def test_status_is_audited(client, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    (entry,) = _audit(db, uid)
    assert entry["actor"] == "owner" and entry["action"] == "تغيير حالة طلب"
    assert entry["details"] == f"الطلب {oid} → Confirmed"


# ── updateStatus: السباق ─────────────────────────────────
def test_two_status_requests_with_the_same_before_count_once(client, app, db, shop, monkeypatch):
    """طلبين فنفس الوقت قراو الطلبية وهي Pending؛ الأول كتب Confirmed. الثاني (Delivered) لازم
    يحسب الفرق من Confirmed (القيمة الحقيقية)، ماشي من Pending."""
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    stale = db.get(f"data/{uid}/orders/{oid}")
    _status(client, shop, oid, "Confirmed")
    _stale_reads(monkeypatch, oid, stale)
    _status(client, shop, oid, "Delivered")
    stats = db.get(f"data/{uid}/stats")
    assert stats["confirmed"] == 1 and stats["delivered"] == 1
    assert db.get(f"data/{uid}/stats/sales/Sac/qty") == 2
    _assert_exact(app, db, uid)


def test_status_transaction_retry_with_stale_value(client, app, db, shop, monkeypatch):
    """Firebase ينادي دالة الـ transaction أولاً بقيمة قديمة ومن بعد بالحالية."""
    uid = shop["uid"]
    oid = _order(client, uid)
    stale = db.get(f"data/{uid}/orders/{oid}")
    _status(client, shop, oid, "Confirmed")
    real = fakes.FakeReference.transaction

    def racing(self, fn):
        if self.path.endswith(f"/orders/{oid}"):
            fn(dict(stale))
        return real(self, fn)
    monkeypatch.setattr(fakes.FakeReference, "transaction", racing)
    _status(client, shop, oid, "Refused")
    stats = db.get(f"data/{uid}/stats")
    assert stats["confirmed"] == 0 and stats["refused"] == 1 and "sales" not in stats
    _assert_exact(app, db, uid)


def test_status_retries_when_product_changed_meanwhile(client, app, db, shop, monkeypatch):
    """editOrder بدّل المنتج بين قرايتنا والـ transaction → نعاودو نقراو، والربح بالمنتج الجديد."""
    uid = shop["uid"]
    oid = _order(client, uid, qty=1)
    stale = db.get(f"data/{uid}/orders/{oid}")
    r = client.post("/api/editOrder", json={"orderId": oid, "data": {"product": "Montre"}}, headers=shop["headers"])
    assert r.status_code == 200
    _stale_reads(monkeypatch, oid, stale, times=1)
    _status(client, shop, oid, "Confirmed")
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["product"] == "Montre"
    assert o["profit"] == pytest.approx((2500.5 - 1800.25) + (400 - 300.5))
    _assert_exact(app, db, uid)


def test_status_gives_up_after_repeated_conflicts(client, app, db, shop, monkeypatch):
    uid = shop["uid"]
    oid = _order(client, uid)
    stale = dict(db.get(f"data/{uid}/orders/{oid}"), product="Montre")
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    _stale_reads(monkeypatch, oid, stale)
    assert _set_status(client, shop["headers"], oid, "Confirmed").status_code == 409
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get(f"data/{uid}/stats") == stats
    assert _audit(db, uid) == []


def test_status_firebase_failure_is_503_and_totals_untouched(client, app, db, shop, monkeypatch):
    uid = shop["uid"]
    oid = _order(client, uid)
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    _fail_order_txn(monkeypatch, oid)
    assert _set_status(client, shop["headers"], oid, "Confirmed").status_code == 503
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get(f"data/{uid}/stats") == stats
    assert _audit(db, uid) == []


# ── updateStatus: طلبية محذوفة، في الحذف، id غير صالح ─────
def test_status_on_order_being_deleted_is_404(client, app, db, shop):
    import services.orders as so
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    db.set(f"data/{uid}/orders/{oid}/deleting", so._now_ms())
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    r = _set_status(client, shop["headers"], oid, "Refused")
    assert r.status_code == 404 and r.get_json()["message"] == "Order not found"
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get(f"data/{uid}/stats") == stats


def test_status_stale_delete_claim_does_not_block(client, app, db, shop):
    import services.orders as so
    uid = shop["uid"]
    oid = _order(client, uid)
    db.set(f"data/{uid}/orders/{oid}/deleting", so._now_ms() - so._DELETE_CLAIM_MS - 1)
    _status(client, shop, oid, "Confirmed")
    assert "deleting" not in db.get(f"data/{uid}/orders/{oid}")
    _assert_exact(app, db, uid)


def test_status_on_deleted_or_unknown_order_is_404(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    assert client.post("/api/deleteOrder", json={"orderId": oid}, headers=shop["headers"]).status_code == 200
    stats = db.get(f"data/{uid}/stats")
    for o in (oid, "ORD-404"):
        r = _set_status(client, shop["headers"], o, "Confirmed")
        assert r.status_code == 404 and r.get_json()["message"] == "Order not found"
    assert db.get(f"data/{uid}/orders/{oid}") is None and db.get(f"data/{uid}/stats") == stats


@pytest.mark.parametrize("oid", ["ORD-1/x", "ORD.1", "a" * 81, "ORD-1#", "ORD[1]"])
def test_status_bad_order_id_is_400(client, db, shop, oid):
    r = _set_status(client, shop["headers"], oid, "Confirmed")
    assert r.status_code == 400 and r.get_json()["message"] == "Invalid order id"
    assert db.get(f"data/{shop['uid']}/orders") is None


def test_status_missing_fields_is_400(client, shop):
    for body in ({"orderId": "ORD-1"}, {"status": "Confirmed"}, {}):
        r = client.post("/api/updateStatus", json=body, headers=shop["headers"])
        assert r.status_code == 400 and r.get_json()["message"] == "Missing fields"


def test_status_isolation_and_permissions(client, app, db, shop, seed_owner, seed_member):
    uid = shop["uid"]
    oid = _order(client, uid)
    before = db.get(f"data/{uid}/orders/{oid}")
    other = seed_owner(username="owner2", uid="2002")
    assert _set_status(client, other["headers"], oid, "Confirmed").status_code == 404
    no = seed_member(shop, "m_no", perms={"products": True})
    assert _set_status(client, no["headers"], oid, "Confirmed").status_code == 403
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get("data/2002/orders") is None
    yes = seed_member(shop, "m_yes", perms={"orders": True})
    assert _set_status(client, yes["headers"], oid, "Confirmed").status_code == 200
    assert _audit(db, uid)[0]["actor"] == "m_yes"
    _assert_exact(app, db, uid)


# ── updateOrderDelivery ──────────────────────────────────
def _set_delivery(client, headers, oid, dtype):
    return client.post("/api/updateOrderDelivery", json={"orderId": oid, "deliveryType": dtype}, headers=headers)


def _delivery(client, owner, oid, dtype):
    r = _set_delivery(client, owner["headers"], oid, dtype)
    assert r.status_code == 200, r.get_json()
    assert r.get_json() == {"status": "ok", "data": True}


def test_delivery_total_and_profit_are_unchanged(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    path = f"data/{uid}/orders/{oid}"
    _delivery(client, shop, oid, "desk")                      # Pending: total يتبدّل، profit = existing
    o = db.get(path)
    assert o["deliveryType"] == "desk" and o["total"] == 1000 * 2 + 300
    assert o["profit"] == 0
    _status(client, shop, oid, "Confirmed")
    _delivery(client, shop, oid, "home")
    o = db.get(path)
    assert o["total"] == 1000 * 2 + 400
    assert o["profit"] == pytest.approx((1000 - 600) * 2 + (400 - 300.5))
    _status(client, shop, oid, "Refused")
    _delivery(client, shop, oid, "desk")
    assert db.get(f"{path}/profit") == -150.75
    assert not db.get(f"{path}/date_delivered")
    _assert_exact(app, db, uid)
    assert [e["action"] for e in _audit(db, uid)] == ["تغيير حالة طلب"] * 2   # التوصيل بلا audit كيما قبل


def test_delivery_with_missing_city_keeps_total_and_profit(client, app, db, shop):
    uid = shop["uid"]
    oid = _order(client, uid)
    _status(client, shop, oid, "Confirmed")
    before = db.get(f"data/{uid}/orders/{oid}")
    db.set(f"data/{uid}/cities/Alger", None)
    _delivery(client, shop, oid, "desk")
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["deliveryType"] == "desk" and o["total"] == before["total"] and o["profit"] == before["profit"]
    _assert_exact(app, db, uid)


def test_two_delivery_requests_with_the_same_before_count_once(client, app, db, shop, monkeypatch):
    """الطلب الأول أكّد الطلبية (Confirmed)، الثاني قرا Pending وبدّل التوصيل. الربح يتحسب مرة،
    والحالة الحقيقية (Confirmed) ما تضيعش."""
    uid = shop["uid"]
    oid = _order(client, uid, qty=2)
    stale = db.get(f"data/{uid}/orders/{oid}")
    _status(client, shop, oid, "Confirmed")
    _stale_reads(monkeypatch, oid, stale)
    _delivery(client, shop, oid, "desk")
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["status"] == "Confirmed" and o["date_sent"]
    assert o["profit"] == pytest.approx((1000 - 600) * 2 + (300 - 200))
    stats = db.get(f"data/{uid}/stats")
    assert stats["confirmed"] == 1 and stats["profitCents"] == round(o["profit"] * 100)
    _assert_exact(app, db, uid)


def test_delivery_retries_when_city_changed_meanwhile(client, app, db, shop, monkeypatch):
    uid = shop["uid"]
    oid = _order(client, uid)
    stale = db.get(f"data/{uid}/orders/{oid}")
    r = client.post("/api/editOrder", json={"orderId": oid, "data": {"city": "Oran"}}, headers=shop["headers"])
    assert r.status_code == 200
    _stale_reads(monkeypatch, oid, stale, times=1)
    _delivery(client, shop, oid, "desk")
    o = db.get(f"data/{uid}/orders/{oid}")
    assert o["city"] == "Oran" and o["total"] == 1000 + 450
    _assert_exact(app, db, uid)


def test_delivery_firebase_failure_is_503_and_totals_untouched(client, app, db, shop, monkeypatch):
    uid = shop["uid"]
    oid = _order(client, uid)
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    _fail_order_txn(monkeypatch, oid)
    assert _set_delivery(client, shop["headers"], oid, "desk").status_code == 503
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get(f"data/{uid}/stats") == stats


def test_delivery_on_deleted_or_claimed_order_is_404(client, app, db, shop):
    import services.orders as so
    uid = shop["uid"]
    oid = _order(client, uid)
    db.set(f"data/{uid}/orders/{oid}/deleting", so._now_ms())
    before, stats = db.get(f"data/{uid}/orders/{oid}"), db.get(f"data/{uid}/stats")
    assert _set_delivery(client, shop["headers"], oid, "desk").status_code == 404
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get(f"data/{uid}/stats") == stats
    db.set(f"data/{uid}/orders/{oid}/deleting", None)
    assert client.post("/api/deleteOrder", json={"orderId": oid}, headers=shop["headers"]).status_code == 200
    for o in (oid, "ORD-404"):
        r = _set_delivery(client, shop["headers"], o, "desk")
        assert r.status_code == 404 and r.get_json()["message"] == "Order not found"
    assert db.get(f"data/{uid}/orders/{oid}") is None


@pytest.mark.parametrize("oid", ["ORD-1/x", "ORD.1", "a" * 81, "ORD-1#"])
def test_delivery_bad_order_id_is_400(client, db, shop, oid):
    r = _set_delivery(client, shop["headers"], oid, "desk")
    assert r.status_code == 400 and r.get_json()["message"] == "Invalid order id"
    assert db.get(f"data/{shop['uid']}/orders") is None


def test_delivery_invalid_fields_is_400(client, shop):
    for body in ({"orderId": "ORD-1", "deliveryType": "air"}, {"deliveryType": "desk"}, {}):
        r = client.post("/api/updateOrderDelivery", json=body, headers=shop["headers"])
        assert r.status_code == 400 and r.get_json()["message"] == "Missing or invalid fields"


def test_delivery_isolation_and_permissions(client, db, shop, seed_owner, seed_member):
    uid = shop["uid"]
    oid = _order(client, uid)
    before = db.get(f"data/{uid}/orders/{oid}")
    other = seed_owner(username="owner2", uid="2002")
    assert _set_delivery(client, other["headers"], oid, "desk").status_code == 404
    no = seed_member(shop, "m_no", perms={"products": True})
    assert _set_delivery(client, no["headers"], oid, "desk").status_code == 403
    assert db.get(f"data/{uid}/orders/{oid}") == before and db.get("data/2002/orders") is None
