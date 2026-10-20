# -*- coding: utf-8 -*-
"""SEC-006 — اسم منتج من طلب عام (بلا حساب) ما يتنفّذش كـ HTML فجداول لوحة التحكم."""
import pathlib
import re

from tests.frontend import dashboard_and_shop

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = dashboard_and_shop()  # HTML + /static/js/* (Phase 4 / F1)
PAYLOAD = '<img src=x onerror="alert(1)">'


def test_public_order_product_reaches_dashboard_as_data(client, db, seed_owner):
    """يوثّق المصدر: addOrder عام ويقبل product نص حر، وgetDashboard يرجّعو كما هو."""
    owner = seed_owner()
    r = client.post("/api/addOrder", json={"userId": owner["uid"], "data": {
        "name": "x", "phone": "0555000000", "city": "Alger", "product": PAYLOAD, "qty": 1}})
    assert r.status_code == 200
    oid = r.get_json()["data"]["orderId"]
    client.post("/api/updateStatus", json={"orderId": oid, "status": "Confirmed"}, headers=owner["headers"])
    d = client.get("/api/getDashboard", headers=owner["headers"]).get_json()["data"]
    assert d["topProducts"][0]["name"] == PAYLOAD  # البيانات تبقى كما هي — التهريب فالواجهة


def _row_builder(tbl_id):
    start = INDEX.index(f'getElementById("{tbl_id}")')
    return INDEX[start:INDEX.index('.join("")', start)]


def test_top_products_row_escapes_every_value():
    row = _row_builder("topProductsTbl")
    assert "esc(p.name)" in row and "esc(p.qty)" in row
    assert not re.search(r'\+p\.(name|qty)\+', row)


def test_low_stock_row_escapes_every_value():
    row = _row_builder("lowStockTbl")
    for f in ("name", "rem", "stat"):
        assert f"esc(p.{f})" in row
    assert not re.search(r'\+p\.(name|rem|stat)\+', row)
