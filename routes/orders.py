# -*- coding: utf-8 -*-
"""طلبات التاجر: القائمة بالصفحات والتغييرات (since/before)، الحالة، ونوع التوصيل. منقول من app.py بلا تغيير (Phase 4 / A7)."""
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from urllib.parse import quote, unquote

import requests
from flask import Blueprint, abort, jsonify, make_response, request, send_from_directory
from markupsafe import escape as _esc

from core.audit import (
    log_audit_entry,
)
from core.db import (
    _fb_get,
    _fb_query,
)
from core.http import (
    _opt_int_arg,
    err_json,
    ok_json,
)
from core.security import (
    require_auth,
    require_perm,
)
from services.orders import (
    _calc_order_profit,
    _save_order,
    _ship_values,
)

import services.orders as _orders_svc  # _now_ms: الاختبارات تعوّضو فـ services.orders

bp = Blueprint("orders", __name__)




_ORDERS_PAGE_MAX         = 500


_ORDERS_CURSOR_MARGIN_MS = 30_000  # تداخل آمن: كتابة بطيئة (retry) ما تضيعش من الـ polling


@bp.route("/api/getOrders", methods=["GET"])
@require_auth
@require_perm("orders")
def api_get_orders():
    """قبل: كل طلبات التاجر فكل نداء (والواجهة تنادي كل 8 ثواني). دابا باستعلامات مفهرسة:
    - بلا معاملات: آخر `limit` طلب (افتراضياً 200) حسب createdAt.
    - before=<createdAt>: الصفحة الأقدم ("تحميل الأقدم").
    - since=<cursor>: غير الطلبات اللي تبدّلت (updatedAt >= cursor). reset=true إذا كثار بزاف.
    - createdAfter=<ms>: الطلبات الجديدة من تاريخ (منحنى الأرباح).
    data تبقى لائحة (الأحدث أولاً)؛ cursor وhasMore فنفس الرد."""
    uid  = request.auth_uid
    path = f"data/{uid}/orders"
    try:
        limit         = max(1, min(int(request.args.get("limit") or 200), _ORDERS_PAGE_MAX))
        since         = _opt_int_arg("since")
        before        = _opt_int_arg("before")
        created_after = _opt_int_arg("createdAfter")
    except ValueError:
        return err_json("Invalid paging parameters")
    started = _orders_svc._now_ms()
    if since is not None:
        cap   = _ORDERS_PAGE_MAX
        found = _fb_query(path, "updatedAt", start_at=since, limit_last=cap + 1)
    elif created_after is not None:
        cap   = _ORDERS_PAGE_MAX
        found = _fb_query(path, "createdAt", start_at=created_after, limit_last=cap + 1)
    else:
        cap   = limit
        found = _fb_query(path, "createdAt", end_at=(before - 1) if before is not None else None,
                          limit_last=cap + 1)
    if found is None:
        return err_json("تعذّر تحميل الطلبات — حاول بعد قليل", 503)
    orders   = [o for o in found.values() if isinstance(o, dict)]
    has_more = len(orders) > cap
    if has_more:
        orders = orders[-cap:]  # النتائج تصاعدية → نخلّيو الأحدث
    orders.sort(key=lambda o: o.get("createdAt") or 0, reverse=True)
    body = {"status": "ok", "data": orders, "hasMore": has_more,
            "cursor": started - _ORDERS_CURSOR_MARGIN_MS}
    if since is not None and has_more:
        body["reset"] = True  # تبدّلات أكثر من الحد — الواجهة تعاود التحميل من الأول
    return jsonify(body)


@bp.route("/api/updateStatus", methods=["POST"])
@require_auth
@require_perm("orders")
def api_update_status():
    body   = request.get_json(silent=True) or {}
    uid    = request.auth_uid
    oid    = str(body.get("orderId") or "").strip()
    status = str(body.get("status")  or "").strip()
    if not oid or not status: return err_json("Missing fields")
    order = _fb_get(f"data/{uid}/orders/{oid}")
    if not order: return err_json("Order not found", 404)
    before = dict(order)
    order["status"] = status
    profit = 0
    now    = time.strftime("%Y-%m-%d %H:%M")
    delivery_type = order.get("deliveryType") or "home"
    if status == "Confirmed" and not order.get("date_sent"):
        order["date_sent"] = now
    if status == "Delivered" and not order.get("date_delivered"):
        order["date_delivered"] = now
    if status in ("Confirmed", "Refused", "Delivered"):
        p_data = _fb_get(f"data/{uid}/products/{order.get('product')}")
        c_data = _fb_get(f"data/{uid}/cities/{order.get('city')}")
        if p_data and c_data:
            profit = _calc_order_profit(p_data, c_data, order.get("qty", 1), delivery_type, status, order.get("profit", 0))
    order["profit"] = profit
    _save_order(uid, oid, order, before=before)
    log_audit_entry(uid, request.auth_member_username or "owner",
                     "تغيير حالة طلب", f"الطلب {oid} → {status}")
    return ok_json(True)


@bp.route("/api/updateOrderDelivery", methods=["POST"])
@require_auth
@require_perm("orders")
def api_update_order_delivery():
    body  = request.get_json(silent=True) or {}
    uid   = request.auth_uid
    oid   = str(body.get("orderId") or "").strip()
    dtype = str(body.get("deliveryType") or "").strip()
    if not oid or dtype not in ("home", "desk"):
        return err_json("Missing or invalid fields")
    order = _fb_get(f"data/{uid}/orders/{oid}")
    if not order: return err_json("Order not found", 404)
    before = dict(order)
    order["deliveryType"] = dtype
    p_data = _fb_get(f"data/{uid}/products/{order.get('product')}")
    c_data = _fb_get(f"data/{uid}/cities/{order.get('city')}")
    if p_data and c_data:
        ship_cust, _ = _ship_values(c_data, dtype)
        order["total"]  = (float(p_data.get("sell", 0)) * int(order.get("qty", 1))) + ship_cust
        order["profit"] = _calc_order_profit(p_data, c_data, order.get("qty", 1), dtype, order.get("status",""), order.get("profit", 0))
    _save_order(uid, oid, order, before=before)
    return ok_json(True)
