# -*- coding: utf-8 -*-
"""المنتجات، المدن، الزبائن، ولوحة القيادة (من المجاميع الجارية). منقول من app.py بلا تغيير (Phase 4 / A7)."""
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
from core.config import (
    BAD_CUSTOMER_THRESHOLD,
    LOW_STOCK_THRESHOLD,
)
from core.db import (
    _fb_delete,
    _fb_get,
    _fb_list,
    _fb_patch,
    _fb_put,
)
from core.http import (
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
    _get_stats,
    _invalidate_store_cache,
    _sold_by_name,
    _stock_fields,
)

bp = Blueprint("catalog", __name__)




# ── Products ──────────────────────────────────────────────
@bp.route("/api/getProducts", methods=["GET"])
@require_auth
@require_perm("products")
def api_get_products():
    uid = request.auth_uid
    # sold/available/stat من stats.sales (بدل القيم المخزّنة اللي كانت تتحدّث غير عند Confirmed)
    sold = _sold_by_name(_get_stats(uid))
    products = []
    for p in _fb_list(f"data/{uid}/products"):
        if isinstance(p, dict):
            p = {**p, **_stock_fields(p, sold.get(p.get("name", ""), 0))}
        products.append(p)
    return ok_json(products)


@bp.route("/api/addProduct", methods=["POST"])
@require_auth
@require_perm("products")
def api_add_product():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    if not d or not d.get("name"): return err_json("Missing fields")
    name     = d["name"]
    existing = _fb_get(f"data/{uid}/products/{name}") or {}
    merged   = {**existing, "name": name,
        "category":    d.get("category",    existing.get("category",    "")),
        "size":        d.get("size",        existing.get("size",        "")),
        "colors":      d.get("colors",      existing.get("colors",      "")),
        "cost":        float(d.get("cost",  existing.get("cost",        0))),
        "sell":        float(d.get("sell",  existing.get("sell",        0))),
        "init":        int(d.get("init",    existing.get("init",        0))),
        "description": d.get("description", existing.get("description", "")),
        "visible":     d.get("visible",     existing.get("visible",     "yes")),
        "image":       d.get("image",       existing.get("image",       "")),
        "images":      d.get("images",      existing.get("images",      [])),
    }
    if not existing:
        merged["sold"]       = 0
        merged["available"]  = int(d.get("init", 0))
        merged["created_at"] = time.time()
        av = merged["available"]
        merged["stat"] = ("Out of Stock" if av <= 0 else "Low Stock" if av <= LOW_STOCK_THRESHOLD else "In Stock")
    _fb_put(f"data/{uid}/products/{name}", merged)
    return ok_json(True)


# ── تعديل منتج موجود (المهمة 3) ────────────────────────────
# بلا تبديل الاسم: هو المفتاح فـ products وفي الطلبيات وفي stats.sales. sold/available/stat
# يتحسبو وقت القراءة (init − stats.sales)، فما يتقبلوش هنا. الطلبيات القديمة تبقى بسعرها.
_PRODUCT_TEXT_FIELDS = {"category": 200, "size": 200, "colors": 500, "description": 5000}
_PRODUCT_MAX_PRICE   = 10_000_000


def _is_url(v):
    return isinstance(v, str) and len(v) <= 2000 and (v == "" or re.match(r"https?://", v) is not None)


def _parse_product_edit(d):
    out = {}
    for key, max_len in _PRODUCT_TEXT_FIELDS.items():
        if key in d:
            v = d[key]
            if not isinstance(v, str) or len(v) > max_len:
                return None, f"{key} غير صالح"
            out[key] = v.strip()
    for key in ("cost", "sell"):
        if key in d:
            v = d[key]
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                return None, f"{key} غير صالح"
            try:
                v = float(v)
            except ValueError:
                return None, f"{key} غير صالح"
            if not 0 <= v <= _PRODUCT_MAX_PRICE:
                return None, f"{key} غير صالح"
            out[key] = v
    if "init" in d:
        v = d["init"]
        if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit())) \
                or not 0 <= int(v) <= 1_000_000:
            return None, "المخزون غير صالح"
        out["init"] = int(v)
    if "visible" in d:
        if d["visible"] not in ("yes", "no"):
            return None, "visible غير صالح"
        out["visible"] = d["visible"]
    if "image" in d:
        if not _is_url(d["image"]):
            return None, "رابط الصورة غير صالح"
        out["image"] = d["image"]
    if "images" in d:
        imgs = d["images"]
        if not isinstance(imgs, list) or len(imgs) > 10 or not all(_is_url(u) and u for u in imgs):
            return None, "الصور غير صالحة"
        out["images"] = imgs
    return out, None


@bp.route("/api/updateProduct", methods=["POST"])
@require_auth
@require_perm("products")
def api_update_product():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") if isinstance(body.get("data"), dict) else {}
    name = str(d.get("name") or "").strip()
    if not name or any(c in name for c in ".$#[]/"):
        return err_json("Missing fields")
    fields, error = _parse_product_edit(d)
    if error:
        return err_json(error)
    existing = _fb_get(f"data/{uid}/products/{name}")
    if not isinstance(existing, dict):
        return err_json("Product not found", 404)
    changes = {k: v for k, v in fields.items() if existing.get(k) != v}
    if not changes:
        return ok_json(True)
    if not _fb_patch(f"data/{uid}/products/{name}", changes):
        return err_json("تعذّر حفظ المنتج — حاول بعد قليل", 503)
    _invalidate_store_cache(uid)
    diff = "، ".join(f"{k}: {_num(existing.get(k, '—'))} → {_num(v)}" for k, v in changes.items()
                    if k not in ("description", "images"))
    hidden = [k for k in changes if k in ("description", "images")]
    log_audit_entry(uid, request.auth_member_username or "owner", "تعديل منتج",
                    f"{name}: " + "، ".join(filter(None, [diff, *hidden])))
    return ok_json(True)


def _num(v):
    """1000.0 → 1000 فالـ audit."""
    return int(v) if isinstance(v, float) and v.is_integer() else v


@bp.route("/api/deleteProduct", methods=["POST"])
@require_auth
@require_perm("products")
def api_delete_product():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    name = str(d.get("name") or "").strip()
    if not name: return err_json("Missing fields")
    _fb_delete(f"data/{uid}/products/{name}")
    log_audit_entry(uid, request.auth_member_username or "owner", f"حذف منتج {name}")
    return ok_json(True)


# ── Cities ────────────────────────────────────────────────
@bp.route("/api/getCities", methods=["GET"])
@require_auth
@require_perm("cities")
def api_get_cities():
    uid    = request.auth_uid
    raw    = _fb_get(f"data/{uid}/cities") or {}
    cities = []
    for k, v in raw.items():
        if isinstance(v, dict):
            v["name"] = v.get("name", k)
            cities.append(v)
    return ok_json(cities)


@bp.route("/api/addCity", methods=["POST"])
@require_auth
@require_perm("cities")
def api_add_city():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    name = str(d.get("name") or "").strip()
    if not name: return err_json("Missing fields")
    if len(name) > 100: return err_json("اسم المدينة طويل جداً")
    _fb_put(f"data/{uid}/cities/{name}", {
        "name": name,
        "costShip": float(d.get("costShip",0)), "custShip": float(d.get("custShip",0)),
        "deskCost": float(d.get("deskCost",0)), "deskCust": float(d.get("deskCust",0)),
        "returnFee": float(d.get("returnFee",0)),
    })
    return ok_json(True)


@bp.route("/api/deleteCity", methods=["POST"])
@require_auth
@require_perm("cities")
def api_delete_city():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    name = str(body.get("name") or "").strip()
    if not name: return err_json("Missing fields")
    _fb_delete(f"data/{uid}/cities/{name}")
    return ok_json(True)


# ── Customers ─────────────────────────────────────────────
@bp.route("/api/getCustomers", methods=["GET"])
@require_auth
@require_perm("customers")
def api_get_customers():
    """من data/{uid}/customers (مجموع لكل رقم) — بدل تنزيل كل الطلبات."""
    uid = request.auth_uid
    raw = _fb_get(f"data/{uid}/customers") or {}
    result = []
    for ph, c in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(c, dict): continue
        stats = {"confirmed": 0, "refused": 0, "delivered": 0, **(c.get("stats") or {})}
        ref = stats["refused"]
        con = stats["confirmed"] + stats["delivered"]
        rating = "Bad" if ref >= BAD_CUSTOMER_THRESHOLD else "Good" if con >= 3 and ref == 0 else "Neutral"
        result.append({"name": c.get("name", ""), "phone": c.get("phone", ""), "city": c.get("city", ""),
                       "totalOrders": c.get("totalOrders", 0), "stats": stats, "type": rating})
    return ok_json(result)


# ── Dashboard ─────────────────────────────────────────────
@bp.route("/api/getDashboard", methods=["GET"])
@require_auth
def api_get_dashboard():
    """من data/{uid}/stats + المنتجات — بدل تنزيل كل الطلبات فكل فتحة للوحة."""
    uid = request.auth_uid
    stats        = _get_stats(uid)
    products_raw = _fb_get(f"data/{uid}/products") or {}
    tot       = _safe_int(stats.get("total"))
    conf      = _safe_int(stats.get("confirmed"))
    ref       = _safe_int(stats.get("refused"))
    delivered = _safe_int(stats.get("delivered"))
    profit    = _safe_int(stats.get("profitCents")) / 100
    sales     = _sold_by_name(stats)
    top_products = sorted([{"name": k, "qty": v} for k, v in sales.items()],
                          key=lambda x: (-x["qty"], x["name"]))[:5]
    low_stock = []
    for p in products_raw.values():
        if not isinstance(p, dict): continue
        remaining = _safe_int(p.get("init", 0)) - sales.get(p.get("name", ""), 0)
        if remaining <= LOW_STOCK_THRESHOLD:
            low_stock.append({"name": p.get("name", ""), "rem": remaining,
                              "stat": "Out of Stock" if remaining <= 0 else "Low Stock"})
    return ok_json({"totalOrders": tot, "confirmed": conf, "refused": ref, "delivered": delivered,
                    "totalProfit": round(profit, 2), "confirmRate": round(conf/tot*100) if tot else 0,
                    "refuseRate": round(ref/tot*100) if tot else 0,
                    "topProducts": top_products, "lowStock": low_stock})
