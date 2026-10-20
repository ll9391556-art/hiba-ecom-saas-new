# -*- coding: utf-8 -*-
"""الطلبات: الحقول المفهرسة (createdAt/updatedAt/phoneDigits)، كتابة الطلبات، المجاميع الجارية
(stats/customers/المخزون/التقييمات)، الأسعار والربح، وكاش المتجر العام.
منقول من app.py بلا تغيير (Phase 4 / A4). app.py يعاود يصدّر الأسماء (إلا _now_ms:
الاختبارات تعدّلو هنا مباشرة فـ services.orders)."""
import hashlib
import logging
import re
import threading
import time

from core.config import LOW_STOCK_THRESHOLD
from core.db import _fb_call, _fb_delete, _fb_get, _fb_keys, _fb_patch, _fb_put, _fb_query, _firebase_ref
from core.http import err_json
from core.util import _mask_id
from core.util import _cents, _safe_int

_store_products_cache = {}


_store_products_cache_lock = threading.Lock()


_STORE_CACHE_TTL = 30  # ثواني — توازن بين حداثة المخزون وتخفيف الحمل


# ── Orders ────────────────────────────────────────────────
# حقول مفهرسة فـ database.rules.json (data/$uid/orders .indexOn): كل كتابة طلب تمر من
# _save_order / _patch_order باش ما تتنساش، وإلا الاستعلامات (trackOrder...) ما تلقاش الطلب.
def _now_ms():
    return int(time.time() * 1000)


def _order_created_ms(order_id, order):
    """createdAt لطلب قديم بلاه: من المعرّف ORD-<ms>، ولا من حقل date، ولا دابا."""
    m = re.fullmatch(r"ORD-(\d{12,14})", str(order_id or ""))
    if m:
        return int(m.group(1))
    try:
        return int(time.mktime(time.strptime(str(order.get("date") or "")[:16], "%Y-%m-%d %H:%M")) * 1000)
    except Exception:
        return _now_ms()


def _phone_digits(phone):
    return re.sub(r"\D", "", str(phone or ""))


def _with_index_fields(order_id, order):
    out = dict(order)
    created = out.get("createdAt")
    if not isinstance(created, (int, float)) or isinstance(created, bool):
        out["createdAt"] = _order_created_ms(order_id, out)
    out["updatedAt"]   = _now_ms()
    out["phoneDigits"] = _phone_digits(out.get("phone"))
    return out


def _save_order(uid, order_id, order, before=None):
    """كتابة كاملة لطلب: createdAt يبقى (أو يتحسب لطلب قديم)، updatedAt وphoneDigits يتحدّثو.
    before = الطلب قبل التعديل (None لطلب جديد) — باش المجاميع تتحدّث بالفرق."""
    after = _with_index_fields(order_id, order)
    ok = _fb_put(f"data/{uid}/orders/{order_id}", after)
    if ok:
        _apply_order_change(uid, before, after)
    return ok


# حقول تأثر على المجاميع — patch فيه وحدة منها يقرا الطلب قبل باش يحسب الفرق
_AGG_ORDER_FIELDS = ("status", "profit", "qty", "product", "phone", "name", "city", "createdAt")


def _patch_order(uid, order_id, patch):
    patch = dict(patch, updatedAt=_now_ms())
    if "phone" in patch:
        patch["phoneDigits"] = _phone_digits(patch["phone"])
    path = f"data/{uid}/orders/{order_id}"
    before = _fb_get(path) if any(k in patch for k in _AGG_ORDER_FIELDS) else None
    ok = _fb_patch(path, patch)
    if ok and isinstance(before, dict):
        _apply_order_change(uid, before, {**before, **patch})
    return ok


# ── المجاميع الجارية (Phase 3 / branch 5) ─────────────────
# بدل تنزيل كل الطلبات فـ getDashboard/getCustomers/المتجر العام:
# - data/{uid}/stats: total/confirmed/delivered/refused، profitCents (سنتيمات صحيحة باش
#   الجمع يكون مضبوط بأي ترتيب)، sales/{key}={name,qty} للطلبات Confirmed/Delivered،
#   ratings/{key}={name,sum,count}. يتحدّث بالفرق (قبل/بعد) فـ transaction مع كل كتابة طلب.
# - data/{uid}/customers/{phoneDigits}: يتعاود حسابه كامل لهاد الرقم فقط (استعلام phoneDigits).
# - المخزون (sold/available/stat) يتحسب وقت القراءة من products + stats.sales.
# _compute_stats/_compute_customers هي "الحساب الكامل" المرجعي — recalc كيستعملهم، والفرق
# مبني بنفس الدوال، فالنتيجة متطابقة.
_SOLD_STATUSES = ("Confirmed", "Delivered")


_STAT_COUNTERS = ("total", "confirmed", "delivered", "refused", "profitCents")


def _agg_key(name):
    """اسم منتج كمفتاح RTDB. أسماء فيها . $ # [ ] / (طلب عام بنص حر) تتحوّل لـ hash، والاسم
    الأصلي يبقى داخل القيمة."""
    s = str(name if name is not None else "")
    if (s and len(s.encode("utf-8")) <= 700 and not any(c in s for c in ".$#[]/")
            and all(ord(c) >= 32 and ord(c) != 127 for c in s)):
        return s
    return "~" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:20]


def _order_contrib(o):
    if not isinstance(o, dict):
        return None
    st = o.get("status", "")
    c = {"total": 1, "confirmed": 0, "delivered": 0, "refused": 0, "profitCents": 0, "sales": {}}
    if st in _SOLD_STATUSES:
        name = str(o.get("product", "") or "")
        c["confirmed"]   = 1
        c["delivered"]   = 1 if st == "Delivered" else 0
        c["profitCents"] = _cents(o.get("profit", 0))
        c["sales"][_agg_key(name)] = (name, _safe_int(o.get("qty", 1), 1))
    elif st == "Refused":
        c["refused"]     = 1
        c["profitCents"] = _cents(o.get("profit", 0))
    return c


def _stats_delta(before, after):
    d, sales = {k: 0 for k in _STAT_COUNTERS}, {}
    for sign, o in ((-1, before), (1, after)):
        c = _order_contrib(o)
        if not c:
            continue
        for k in _STAT_COUNTERS:
            d[k] += sign * c[k]
        for key, (name, qty) in c["sales"].items():
            n, q = sales.get(key, (name, 0))
            sales[key] = (n, q + sign * qty)
    sales = {k: v for k, v in sales.items() if v[1]}
    if not any(d.values()) and not sales:
        return None
    d["sales"] = sales
    return d


def _add_to_stats(stats, delta):
    stats = dict(stats) if isinstance(stats, dict) else {}
    for k in _STAT_COUNTERS:
        stats[k] = _safe_int(stats.get(k, 0)) + delta.get(k, 0)
    sales = dict(stats.get("sales") or {})
    for key, (name, q) in delta.get("sales", {}).items():
        entry = sales.get(key) if isinstance(sales.get(key), dict) else {"name": name, "qty": 0}
        qty = _safe_int(entry.get("qty", 0)) + q
        if qty:
            sales[key] = {"name": entry.get("name", name), "qty": qty}
        else:
            sales.pop(key, None)
    if sales:
        stats["sales"] = sales
    else:
        stats.pop("sales", None)  # RTDB ما يخزّنش {} — نفس الشكل فالحساب والتخزين
    return stats


def _compute_stats(orders, ratings):
    """الحساب الكامل المرجعي لـ data/{uid}/stats (recalc / backfill)."""
    stats = {}
    for o in (orders or {}).values():
        delta = _stats_delta(None, o)
        if delta:
            stats = _add_to_stats(stats, delta)
    stats = _add_to_stats(stats, {})  # العدادات موجودة حتى بلا طلبات
    rmap = {}
    for product, rs in (ratings or {}).items():
        vals = [_safe_int(r.get("rating", 0)) for r in (rs or {}).values() if isinstance(r, dict)] \
            if isinstance(rs, dict) else []
        if vals:
            rmap[_agg_key(product)] = {"name": product, "sum": sum(vals), "count": len(vals)}
    if rmap:
        stats["ratings"] = rmap
    return stats


def _customer_from_orders(items):
    """items = [(order_id, order)] لنفس الرقم. الاسم/المدينة من أقدم طلب (createdAt ثم المعرّف)."""
    rows = sorted(((k, o) for k, o in items if isinstance(o, dict)),
                  key=lambda kv: (_safe_int(kv[1].get("createdAt"), 0), str(kv[0])))
    if not rows:
        return None
    first = rows[0][1]
    st = [o.get("status", "") for _, o in rows]
    return {"name": first.get("name", ""), "phone": first.get("phone", ""), "city": first.get("city", ""),
            "totalOrders": len(rows),
            "stats": {"confirmed": st.count("Confirmed"), "refused": st.count("Refused"),
                      "delivered": st.count("Delivered")}}


def _compute_customers(orders):
    """الحساب الكامل المرجعي لـ data/{uid}/customers."""
    groups = {}
    for k, o in (orders or {}).items():
        if isinstance(o, dict):
            ph = _phone_digits(o.get("phone"))
            if ph:
                groups.setdefault(ph, []).append((k, o))
    return {ph: _customer_from_orders(items) for ph, items in groups.items()}


def _refresh_customer(uid, digits):
    found = _fb_query(f"data/{uid}/orders", "phoneDigits", equal_to=digits)
    if found is None:
        logging.error(f"customer refresh failed for {_mask_id(digits)} — شغّل /api/recalcStats")
        return
    cust = _customer_from_orders(found.items())
    if cust:
        _fb_put(f"data/{uid}/customers/{digits}", cust)
    else:
        _fb_delete(f"data/{uid}/customers/{digits}")


def _invalidate_store_cache(uid):
    with _store_products_cache_lock:
        _store_products_cache.pop(str(uid), None)


_CUSTOMER_FIELDS = ("status", "phone", "name", "city", "createdAt")


def _apply_order_change(uid, before, after):
    """يحدّث المجاميع بعد كتابة طلب (before=None: طلب جديد، after=None: طلب محذوف)."""
    delta = _stats_delta(before, after)
    if delta:
        try:
            _firebase_ref(f"data/{uid}/stats").transaction(lambda cur: _add_to_stats(cur, delta))
        except Exception as e:
            logging.error(f"stats update failed ({type(e).__name__}) — شغّل /api/recalcStats")
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    if not b or not a or any(b.get(f) != a.get(f) for f in _CUSTOMER_FIELDS):
        for ph in sorted({_phone_digits(b.get("phone")), _phone_digits(a.get("phone"))} - {""}):
            _refresh_customer(uid, ph)
    _invalidate_store_cache(uid)


def _add_rating_to_stats(uid, product, rating):
    key = _agg_key(product)
    def _txn(cur):
        cur = dict(cur) if isinstance(cur, dict) else {}
        ratings = dict(cur.get("ratings") or {})
        r = ratings.get(key) if isinstance(ratings.get(key), dict) else {"name": product, "sum": 0, "count": 0}
        ratings[key] = {"name": r.get("name", product), "sum": _safe_int(r.get("sum")) + int(rating),
                        "count": _safe_int(r.get("count")) + 1}
        cur["ratings"] = ratings
        return cur
    try:
        _firebase_ref(f"data/{uid}/stats").transaction(_txn)
    except Exception as e:
        logging.error(f"rating stats update failed ({type(e).__name__}) — شغّل /api/recalcStats")
    _invalidate_store_cache(uid)


def _get_stats(uid):
    s = _fb_get(f"data/{uid}/stats")
    return s if isinstance(s, dict) else {}


def _sold_by_name(stats):
    return {e.get("name", ""): _safe_int(e.get("qty"))
            for e in (stats.get("sales") or {}).values() if isinstance(e, dict)}


def _stock_fields(product, sold):
    init      = _safe_int(product.get("init", 0))
    available = max(0, init - sold)
    stat      = ("Out of Stock" if available <= 0
                 else "Low Stock" if available <= LOW_STOCK_THRESHOLD else "In Stock")
    return {"sold": sold, "available": available, "stat": stat}


def _recompute_aggregates(uid):
    """recalc كامل لتاجر واحد (قراءة كل الطلبات مرة). ما يكتب والو إذا القراءة فشلات —
    باش خطأ شبكة ما يصفّرش المجاميع."""
    try:
        orders  = _fb_call(lambda: _firebase_ref(f"data/{uid}/orders").get()) or {}
        ratings = _fb_call(lambda: _firebase_ref(f"data/{uid}/ratings").get()) or {}
    except Exception as e:
        logging.error(f"recompute read failed for {uid}: {type(e).__name__}")
        return None
    orders  = orders if isinstance(orders, dict) else {}
    ratings = ratings if isinstance(ratings, dict) else {}
    stats, customers = _compute_stats(orders, ratings), _compute_customers(orders)
    if not _fb_put(f"data/{uid}/stats", stats):
        return None
    ok = _fb_put(f"data/{uid}/customers", customers) if customers else _fb_delete(f"data/{uid}/customers")
    if not ok:
        return None
    _invalidate_store_cache(uid)
    return {"orders": len(orders), "customers": len(customers)}


def _ship_values(c_data, delivery_type):
    is_desk = delivery_type == "desk"
    ship_cust = float(c_data.get("deskCust", 0)) if is_desk else float(c_data.get("custShip", 0))
    ship_cost = float(c_data.get("deskCost", 0)) if is_desk else float(c_data.get("costShip", 0))
    return ship_cust, ship_cost


def _calc_order_profit(p_data, c_data, qty, delivery_type, status, existing_profit=0.0):
    ship_cust, ship_cost = _ship_values(c_data, delivery_type)
    if status in ("Confirmed", "Delivered"):
        return ((float(p_data.get("sell", 0)) - float(p_data.get("cost", 0))) * int(qty)) + (ship_cust - ship_cost)
    elif status == "Refused":
        return -float(c_data.get("returnFee", 0))
    return existing_profit


def _rebuild_order_fields():
    uids = _fb_keys("data")
    if uids is None:
        return err_json("Firebase unavailable", 503)
    now = _now_ms()
    merchants = checked = updated = 0
    for uid in uids:
        orders = _fb_get(f"data/{uid}/orders")
        if not isinstance(orders, dict):
            continue
        merchants += 1
        patch = {}
        for oid, o in orders.items():
            if not isinstance(o, dict):
                continue
            checked += 1
            fix = {}
            created = o.get("createdAt")
            if not isinstance(created, (int, float)) or isinstance(created, bool):
                fix["createdAt"] = _order_created_ms(oid, o)
            updated_at = o.get("updatedAt")
            if not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool):
                fix["updatedAt"] = now
            digits = _phone_digits(o.get("phone"))
            if o.get("phoneDigits") != digits:
                fix["phoneDigits"] = digits
            if fix:
                updated += 1
                patch.update({f"{oid}/{k}": v for k, v in fix.items()})
        if patch and not _fb_patch(f"data/{uid}/orders", patch):
            return err_json(f"write failed for merchant {uid}", 500)
    logging.info(f"🔧 rebuildIndexes: orders merchants={merchants} checked={checked} updated={updated}")
    return {"merchants": merchants, "checked": checked, "updated": updated}
