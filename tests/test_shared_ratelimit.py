# -*- coding: utf-8 -*-
"""Phase 3 / branch 7 — حدود معدل مشتركة بين كل workers (عدّاد Firebase بـ transaction)،
بمفاتيح مهشّرة (بلا IP ولا اسم خام)، وتمرّ الطلب إذا Firebase طاح. وسلة بعدة منتجات تدوز."""
import json

import pytest

from tests import fakes

A_IP, B_IP = "203.0.113.7", "198.51.100.9"


@pytest.fixture
def store(db, seed_owner):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/products/Sac", {"name": "Sac", "init": 50, "sell": 1000})
    db.set(f"data/{owner['uid']}/cities/Alger", {"name": "Alger", "custShip": 400})
    return owner


@pytest.fixture
def small_limits(app, monkeypatch):
    monkeypatch.setitem(app._RATE_LIMITS, "order_ip_store", (3, 600))
    monkeypatch.setitem(app._RATE_LIMITS, "order_store", (5, 3600))
    monkeypatch.setitem(app._RATE_LIMITS, "track_ip", (100, 600))
    monkeypatch.setitem(app._RATE_LIMITS, "track_ip_store", (2, 600))
    monkeypatch.setitem(app._RATE_LIMITS, "coupon_ip_store", (2, 600))
    monkeypatch.setitem(app._RATE_LIMITS, "login_ip", (100, 600))
    monkeypatch.setitem(app._RATE_LIMITS, "login_user", (3, 600))


def _new_worker(app):
    """worker آخر: الذاكرة المحلية فارغة، Firebase نفسو."""
    for name in ("last_msg_time", "_login_attempts"):
        getattr(app, name).clear()


def _order(client, uid, ip=A_IP, phone="0555123456"):
    return client.post("/api/addOrder", environ_overrides={"REMOTE_ADDR": ip}, json={
        "userId": uid, "data": {"name": "x", "phone": phone, "city": "Alger", "product": "Sac", "qty": 1}})


def test_ten_item_cart_from_one_customer_goes_through(client, db, store):
    """السلة تبعث طلب لكل منتج — قبل: الحد ip:phone (15 ثانية) كان يرفض المنتج الثاني."""
    codes = [_order(client, store["uid"]).status_code for _ in range(10)]
    assert codes == [200] * 10
    assert len(db.get(f"data/{store['uid']}/orders")) == 10


def test_add_order_limit_is_shared_across_workers(client, app, store, small_limits):
    uid = store["uid"]
    for _ in range(3):
        assert _order(client, uid).status_code == 200
        _new_worker(app)
    assert _order(client, uid).status_code == 429
    assert _order(client, uid, ip=B_IP).status_code == 200   # زبون آخر
    assert _order(client, uid, ip=B_IP).status_code == 200
    assert _order(client, uid, ip="192.0.2.1").status_code == 429  # حد المتجر (5)


def test_unknown_store_does_not_consume_the_limit(client, store, small_limits):
    for _ in range(5):
        assert _order(client, "999999").status_code == 404
    assert _order(client, store["uid"]).status_code == 200


def test_track_order_limit(client, app, store, small_limits):
    uid = store["uid"]
    get = lambda: client.get(f"/api/trackOrder?userId={uid}&phone=0555", environ_overrides={"REMOTE_ADDR": A_IP})
    assert [get().status_code for _ in range(2)] == [200, 200]
    _new_worker(app)
    assert get().status_code == 429


def test_coupon_validation_limit(client, db, app, store, small_limits):
    uid = store["uid"]
    db.set(f"data/{uid}/coupons/PROMO", {"code": "PROMO", "type": "percent", "value": 10, "active": True})
    get = lambda code: client.get(f"/api/coupons/validate?userId={uid}&code={code}&subtotal=1000",
                                  environ_overrides={"REMOTE_ADDR": A_IP})
    assert get("GUESS1").status_code == 404
    assert get("PROMO").status_code == 200
    _new_worker(app)
    assert get("GUESS2").status_code == 429


def test_login_limit_per_username_across_ips(client, app, store, small_limits):
    """password spraying من IPs مختلفة على نفس الحساب: الحد المحلي (ip+user) ما كانش يحبسو."""
    def login(ip):
        return client.post("/api/login", environ_overrides={"REMOTE_ADDR": ip},
                           json={"username": store["username"], "password": "wrong-pass"})
    for i in range(3):
        assert login(f"192.0.2.{i}").status_code == 401
    assert login("192.0.2.50").status_code == 429


def test_fail_open_when_firebase_is_down(client, app, store, small_limits, monkeypatch):
    class UnavailableError(Exception):
        pass

    real_txn = fakes.FakeReference.transaction

    def txn(self, fn):
        if self.path.startswith("/ratelimits/"):
            raise UnavailableError("503")
        return real_txn(self, fn)

    monkeypatch.setattr(fakes.FakeReference, "transaction", txn)
    assert [_order(client, store["uid"]).status_code for _ in range(5)] == [200] * 5


def test_keys_are_hashed(client, db, store, small_limits):
    _order(client, store["uid"])
    client.post("/api/login", environ_overrides={"REMOTE_ADDR": A_IP},
                json={"username": store["username"], "password": "wrong-pass"})
    dump = json.dumps(db.get("ratelimits"))
    assert db.get("ratelimits") and A_IP not in dump and store["username"] not in dump


def test_cleanup_deletes_only_old_windows(app, db):
    now = 1_700_000_000
    w = now // 600
    db.set("ratelimits/order_ip_store", {str(w): {"k": 1}, str(w - 1): {"k": 1}, str(w - 5): {"k": 1}})
    app._cleanup_shared_limits(now)
    assert set(db.get("ratelimits/order_ip_store")) == {str(w), str(w - 1)}
