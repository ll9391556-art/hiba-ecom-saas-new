# -*- coding: utf-8 -*-
"""طلبات التاجر: القائمة بالصفحات والتغييرات (since/before)، الحالة، ونوع التوصيل. منقول من app.py بلا تغيير (Phase 4 / A7)."""
import datetime
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
from core.util import (
    _safe_int,
)
from services.orders import (
    OrderConflict,
    OrderGone,
    _apply_status_dates,
    _calc_order_profit,
    _claimed,
    _mutate_order,
    _phone_digits,
    _save_order,
    _ship_values,
    _valid_order_id,
)

from services.users import (
    planHas_server,
)

import services.orders as _orders_svc  # _now_ms: الاختبارات تعوّضو فـ services.orders

bp = Blueprint("orders", __name__)




_ORDERS_PAGE_MAX         = 500


_ORDERS_CURSOR_MARGIN_MS = 30_000  # تداخل آمن: كتابة بطيئة (retry) ما تضيعش من الـ polling


# ── تصدير الطلبات لـ Excel (من Starter وفوق) ───────────────
# CSV بـ UTF-8 BOM وفاصل ";" — Excel بالفرنسية (أغلب الحواسيب فالجزائر) يحلّو بالأعمدة
# والعربية صحيحة، بلا مكتبة جديدة. استعلام createdAt (مفهرس) بدل تنزيل كل الطلبات.
_EXPORT_MAX_ROWS   = 5000
_EXPORT_DEFAULT_MS = 90 * 86_400_000
_EXPORT_COLUMNS = [("ID", "id"), ("Date", "createdAt"), ("Nom / الاسم", "name"), ("Téléphone / الهاتف", "phone"),
                   ("Wilaya / الولاية", "city"), ("Adresse / العنوان", "address"), ("Produit / المنتج", "product"),
                   ("Qté / الكمية", "qty"), ("Livraison / التوصيل", "deliveryType"), ("Frais / الشحن", "shipping"),
                   ("Total / المجموع", "total"), ("Statut / الحالة", "status"), ("Source / المصدر", "source"),
                   ("Coupon", "couponCode")]
_DZ_TZ = datetime.timezone(datetime.timedelta(hours=1))  # الجزائر UTC+1 بلا توقيت صيفي


def _csv_cell(v):
    s = "" if v is None else str(v)
    # CSV injection: خلية تبدا بـ = + - @ (أو tab/CR) يحسبها Excel معادلة — نسبقوها بـ '
    if s[:1] in ("=", "@", "\t", "\r") or (s[:1] in ("+", "-") and not s[1:].replace(" ", "").isdigit()):
        s = "'" + s
    if any(ch in s for ch in (";", '"', "\n", "\r")):
        s = '"' + s.replace('"', '""') + '"'
    return s


def _export_value(order, key):
    v = order.get(key)
    if key == "createdAt" and isinstance(v, (int, float)) and v > 0:
        return datetime.datetime.fromtimestamp(v / 1000, _DZ_TZ).strftime("%Y-%m-%d %H:%M")
    return v


@bp.route("/api/exportOrders", methods=["GET"])
@require_auth
@require_perm("orders")
def api_export_orders():
    uid = request.auth_uid
    if not planHas_server(uid, "export"):
        return err_json("تصدير الطلبات متاح من باقة Starter وفوق", 403)
    try:
        to_ms   = _opt_int_arg("to")
        from_ms = _opt_int_arg("from")
    except ValueError:
        return err_json("Invalid date range")
    to_ms   = to_ms if to_ms is not None else _orders_svc._now_ms()
    from_ms = from_ms if from_ms is not None else to_ms - _EXPORT_DEFAULT_MS
    found = _fb_query(f"data/{uid}/orders", "createdAt", start_at=from_ms, end_at=to_ms,
                      limit_last=_EXPORT_MAX_ROWS)
    if found is None:
        return err_json("تعذّر تحميل الطلبات — حاول بعد قليل", 503)
    orders = sorted((o for o in found.values() if isinstance(o, dict)),
                    key=lambda o: o.get("createdAt") or 0, reverse=True)
    lines = [";".join(h for h, _ in _EXPORT_COLUMNS)]
    lines += [";".join(_csv_cell(_export_value(o, k)) for _, k in _EXPORT_COLUMNS) for o in orders]
    log_audit_entry(uid, getattr(request, "auth_member_username", "") or "owner", f"تصدير {len(orders)} طلب")
    resp = make_response("\ufeff" + "\r\n".join(lines) + "\r\n")
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    stamp = datetime.datetime.now(_DZ_TZ).strftime("%Y%m%d")
    resp.headers["Content-Disposition"] = f'attachment; filename="orders-{stamp}.csv"'
    return resp


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
    _apply_status_dates(order, status, now)
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


# ── تعديل طلب (المهمة 3) ──────────────────────────────────
_ORDER_STATUSES = ("Pending", "Confirmed", "Delivered", "Refused", "No Answer")
_EDIT_FIELDS    = ("name", "phone", "product", "qty", "city", "deliveryType", "total", "status")
_PRICING_FIELDS = ("product", "qty", "city", "deliveryType", "total", "status")
_MAX_ORDER_TOTAL = 10_000_000


def _parse_order_edit(d):
    """whitelist + فحص لحقول التعديل. يرجّع (fields, None) ولا (None, رسالة الخطأ).
    profit/id/createdAt/source/couponCode/discountApplied... ما يتقبلوش من الواجهة أبداً."""
    if not isinstance(d, dict):
        return None, "Missing fields"
    out = {}
    if "name" in d:
        name = str(d.get("name") or "").strip()
        if not 1 <= len(name) <= 100:
            return None, "الاسم غير صالح"
        out["name"] = name
    if "phone" in d:
        phone = str(d.get("phone") or "").strip()
        if len(phone) > 30 or not 9 <= len(_phone_digits(phone)) <= 15:
            return None, "رقم الهاتف غير صالح"
        out["phone"] = phone
    for key, msg in (("product", "المنتج غير صالح"), ("city", "الولاية غير صالحة")):
        if key in d:
            v = str(d.get(key) or "").strip()
            if not 1 <= len(v) <= 200:
                return None, msg
            out[key] = v
    if "qty" in d:
        q = d.get("qty")
        try:
            q = int(str(q).strip()) if not isinstance(q, bool) else 0
        except ValueError:
            q = 0
        if not 1 <= q <= 999:
            return None, "الكمية غير صالحة"
        out["qty"] = q
    if "deliveryType" in d:
        if d.get("deliveryType") not in ("home", "desk"):
            return None, "نوع التوصيل غير صالح"
        out["deliveryType"] = d["deliveryType"]
    if "status" in d:
        if d.get("status") not in _ORDER_STATUSES:
            return None, "الحالة غير صالحة"
        out["status"] = d["status"]
    if "total" in d:
        t = d.get("total")
        try:
            t = float(t) if not isinstance(t, bool) else -1.0
        except (TypeError, ValueError):
            t = -1.0
        if not 0 <= t <= _MAX_ORDER_TOTAL:  # يرفض NaN كذلك
            return None, "المجموع غير صالح"
        out["total"] = round(t, 2)
    return out, None


def _price_order(order, p_data, c_data, total_given):
    """المجموع والربح بعد تعديل. المجموع التلقائي = sell×qty + ship_cust − discountApplied؛ مجموع
    مكتوب باليد (مختلف على التلقائي) يبقى، والربح منو: total − cost×qty − ship_cost (نفس المعادلة
    كي يكون المجموع عادي). الربح بنفس قواعد updateStatus. منتج ولا ولاية ماعادوش: القيم القديمة."""
    status = order.get("status", "")
    dtype  = order.get("deliveryType") or "home"
    qty    = _safe_int(order.get("qty", 1), 1)
    known  = isinstance(p_data, dict) and isinstance(c_data, dict)
    auto   = None
    if known:
        ship_cust, ship_cost = _ship_values(c_data, dtype)
        auto = max(0, round(float(p_data.get("sell", 0)) * qty + ship_cust
                            - float(order.get("discountApplied") or 0), 2))
    manual = total_given and (auto is None or abs(float(order.get("total") or 0) - auto) > 0.005)
    if not manual and auto is not None:
        order["total"] = auto
    if status in ("Confirmed", "Delivered"):
        if known:
            order["profit"] = (round(order["total"] - float(p_data.get("cost", 0)) * qty - ship_cost, 2)
                               if manual else _calc_order_profit(p_data, c_data, qty, dtype, status))
    elif status == "Refused":
        if isinstance(c_data, dict):
            order["profit"] = -float(c_data.get("returnFee", 0))
    else:
        order["profit"] = 0


def _order_diff(before, after, keys):
    return [f"{k}: {before.get(k, '—')} → {after.get(k, '—')}" for k in keys if before.get(k) != after.get(k)]


def _actor():
    return getattr(request, "auth_member_username", "") or "owner"


@bp.route("/api/editOrder", methods=["POST"])
@require_auth
@require_perm("orders")
def api_edit_order():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    oid  = body.get("orderId")
    if not _valid_order_id(oid):
        return err_json("Invalid order id")
    fields, error = _parse_order_edit(body.get("data"))
    if error:
        return err_json(error)
    order = _fb_get(f"data/{uid}/orders/{oid}")
    if not isinstance(order, dict) or _claimed(order):
        return err_json("Order not found", 404)
    # المنتج والولاية يتقراو قبل الـ transaction (دالتها لازم تكون بلا شبكة)
    product = fields.get("product", order.get("product"))
    city    = fields.get("city", order.get("city"))
    p_data  = _fb_get(f"data/{uid}/products/{product}") if product else None
    c_data  = _fb_get(f"data/{uid}/cities/{city}") if city else None
    if "product" in fields and fields["product"] != order.get("product") and not isinstance(p_data, dict):
        return err_json("المنتج غير موجود")
    if "city" in fields and fields["city"] != order.get("city") and not isinstance(c_data, dict):
        return err_json("الولاية غير موجودة")
    now = time.strftime("%Y-%m-%d %H:%M")

    def build(cur):
        if (cur.get("product"), cur.get("city")) != (order.get("product"), order.get("city")):
            raise OrderConflict()  # p_data/c_data اللي قريناهم ماعادوش تاع هاد الطلب
        new = {**cur, **fields}
        if any(k in fields and fields[k] != cur.get(k) for k in _PRICING_FIELDS):
            _price_order(new, p_data, c_data, "total" in fields)
        if "status" in fields:
            _apply_status_dates(new, new["status"], now)
        return None if new == cur else new

    try:
        before, after = _mutate_order(uid, oid, build)
    except OrderGone:
        return err_json("Order not found", 404)
    except OrderConflict:
        return err_json("الطلب تبدّل فنفس الوقت — عاود حمّل الطلبات وحاول", 409)
    except Exception as e:
        logging.error(f"editOrder failed ({type(e).__name__})")
        return err_json("تعذّر حفظ التعديل — حاول بعد قليل", 503)
    if after is None:
        return ok_json(before)
    log_audit_entry(uid, _actor(), "تعديل طلب",
                    f"الطلب {oid}: " + "، ".join(_order_diff(before, after, _EDIT_FIELDS)))
    return ok_json(after)
