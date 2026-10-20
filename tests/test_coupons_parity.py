# -*- coding: utf-8 -*-
"""Phase 4 / A4 — توصيف سلوك الكوبونات قبل توحيد المنطق (services/coupons.py): نفس الرسائل
ونفس الخصم فالمتجر العام (/api/coupons/validate) وفـ addOrder (_validate_and_apply_coupon)."""
import time

import pytest

TODAY = time.strftime("%Y-%m-%d")
COUPONS = {
    "PCT10":   {"code": "PCT10", "type": "percent", "value": 10, "active": True},
    "FIX300":  {"code": "FIX300", "type": "fixed", "value": 300, "active": True},
    "BIGFIX":  {"code": "BIGFIX", "type": "fixed", "value": 5000, "active": True},
    "OFF":     {"code": "OFF", "type": "percent", "value": 10, "active": False},
    "OLD":     {"code": "OLD", "type": "percent", "value": 10, "active": True, "expiresAt": "2000-01-01"},
    "TODAY":   {"code": "TODAY", "type": "percent", "value": 10, "active": True, "expiresAt": TODAY},
    "USEDUP":  {"code": "USEDUP", "type": "percent", "value": 10, "active": True, "maxUses": 2, "usedCount": 2},
    "MIN2000": {"code": "MIN2000", "type": "percent", "value": 10, "active": True, "minOrderTotal": 2000},
}


@pytest.fixture
def store(db, seed_owner):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/coupons", COUPONS)
    return owner


@pytest.mark.parametrize("code,status,expect", [
    ("pct10",   200, {"discountAmount": 100.0, "type": "percent", "value": 10}),
    ("FIX300",  200, {"discountAmount": 300, "type": "fixed"}),
    ("BIGFIX",  200, {"discountAmount": 1000}),            # ما يفوتش المجموع
    ("TODAY",   200, {"discountAmount": 100.0}),
    ("NOPE",    404, "كود الخصم غير موجود"),
    ("OFF",     400, "كود الخصم غير فعّال حالياً"),
    ("OLD",     400, "انتهت صلاحية كود الخصم"),
    ("USEDUP",  400, "تم استنفاد هذا الكود بالكامل"),
    ("MIN2000", 400, "الحد الأدنى للطلب لاستعمال هذا الكود هو 2000.0"),
])
def test_public_validate(client, store, code, status, expect):
    r = client.get(f"/api/coupons/validate?userId={store['uid']}&code={code}&subtotal=1000")
    assert r.status_code == status
    body = r.get_json()
    if status == 200:
        assert {k: body["data"][k] for k in expect} == expect
        assert body["data"]["code"] == code.upper() and body["data"]["appliesTo"] == "all"
    else:
        assert body["message"] == expect


@pytest.mark.parametrize("code,expect", [
    ("pct10", (100.0, "PCT10")), ("FIX300", (300.0, "FIX300")), ("BIGFIX", (1000.0, "BIGFIX")),
    ("TODAY", (100.0, "TODAY")), ("NOPE", (0.0, None)), ("OFF", (0.0, None)), ("OLD", (0.0, None)),
    ("USEDUP", (0.0, None)), ("MIN2000", (0.0, None)), ("", (0.0, None)),
])
def test_order_path(app, store, code, expect):
    assert app._validate_and_apply_coupon(store["uid"], code, 1000) == expect


def test_add_order_applies_coupon(client, db, store):
    uid = store["uid"]
    db.set(f"data/{uid}/products/Sac", {"name": "Sac", "sell": 1000})
    db.set(f"data/{uid}/cities/Alger", {"name": "Alger", "custShip": 400})
    r = client.post("/api/addOrder", json={"userId": uid, "data": {
        "name": "x", "phone": "0555", "city": "Alger", "product": "Sac", "qty": 1, "couponCode": "pct10",
        "discountApplied": 999999}})
    oid = r.get_json()["data"]["orderId"]
    order = db.get(f"data/{uid}/orders/{oid}")
    assert order["couponCode"] == "PCT10" and order["discountApplied"] == 140.0 and order["total"] == 1260.0
