# -*- coding: utf-8 -*-
"""
موديول أكواد الخصم والقسائم — مستقل تماماً عن app.py
قاعدة البيانات: data/{uid}/coupons/{code}
"""
import re
import time
import random
import string
from flask import Blueprint, request

# استيراد الدوال والديكوريتورز الجاهزة من الملف الرئيسي — بلا إعادة كتابة
from app import (
    require_auth, require_perm, _fb_get, _fb_put, _fb_patch, _fb_delete,
    ok_json, err_json, _any_shared_limited,
)
from services.coupons import coupon_discount, coupon_problem

discounts_bp = Blueprint("discounts", __name__)


def _gen_code(length=8):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def _clean_coupon_input(d, existing=None):
    existing = existing or {}
    ctype = str(d.get("type") or existing.get("type") or "percent").strip().lower()
    if ctype not in ("percent", "fixed"):
        ctype = "percent"
    try:
        value = float(d.get("value", existing.get("value", 0)))
    except Exception:
        value = 0.0
    if ctype == "percent":
        value = max(0.0, min(100.0, value))
    else:
        value = max(0.0, value)
    try:
        min_total = float(d.get("minOrderTotal", existing.get("minOrderTotal", 0)))
    except Exception:
        min_total = 0.0
    try:
        max_uses = int(d.get("maxUses", existing.get("maxUses", 0)) or 0)
    except Exception:
        max_uses = 0
    applies_to = d.get("appliesTo", existing.get("appliesTo", "all"))
    if applies_to != "all" and not isinstance(applies_to, list):
        applies_to = "all"
    return {
        "type": ctype,
        "value": value,
        "minOrderTotal": min_total,
        "maxUses": max_uses,             # 0 = بلا حد
        "usedCount": int(existing.get("usedCount", 0)),
        "expiresAt": str(d.get("expiresAt", existing.get("expiresAt", "")) or ""),
        "active": bool(d.get("active", existing.get("active", True))),
        "appliesTo": applies_to,          # "all" أو ["اسم منتج", ...]
    }


@discounts_bp.route("/api/coupons/list", methods=["GET"])
@require_auth
@require_perm("store")
def list_coupons():
    uid = request.auth_uid
    raw = _fb_get(f"data/{uid}/coupons") or {}
    items = []
    if isinstance(raw, dict):
        for code, c in raw.items():
            if isinstance(c, dict):
                items.append({**c, "code": code})
    items.sort(key=lambda x: x.get("code", ""))
    return ok_json(items)


@discounts_bp.route("/api/coupons/create", methods=["POST"])
@require_auth
@require_perm("store")
def create_coupon():
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    code = re.sub(r"[^A-Za-z0-9_-]", "", str(body.get("code") or "").strip().upper())
    if not code:
        code = _gen_code()
    if _fb_get(f"data/{uid}/coupons/{code}"):
        return err_json("هذا الكود مستعمل من قبل", 409)
    record = _clean_coupon_input(body)
    record["created_at"] = time.strftime("%Y-%m-%d %H:%M")
    _fb_put(f"data/{uid}/coupons/{code}", record)
    return ok_json({"code": code, **record})


@discounts_bp.route("/api/coupons/update", methods=["POST"])
@require_auth
@require_perm("store")
def update_coupon():
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    code = str(body.get("code") or "").strip().upper()
    if not code:
        return err_json("Missing code")
    existing = _fb_get(f"data/{uid}/coupons/{code}")
    if not existing:
        return err_json("القسيمة غير موجودة", 404)
    record = _clean_coupon_input(body, existing)
    _fb_patch(f"data/{uid}/coupons/{code}", record)
    return ok_json(True)


@discounts_bp.route("/api/coupons/delete", methods=["POST"])
@require_auth
@require_perm("store")
def delete_coupon():
    uid = request.auth_uid
    code = str((request.get_json(silent=True) or {}).get("code") or "").strip().upper()
    if not code:
        return err_json("Missing code")
    _fb_delete(f"data/{uid}/coupons/{code}")
    return ok_json(True)


@discounts_bp.route("/api/coupons/validate", methods=["GET"])
def validate_coupon_public():
    """مسار عام (بدون توكن) — تستدعيه صفحة المتجر العامة وقت إدخال كود الخصم."""
    uid = request.args.get("userId", "").strip()
    code = str(request.args.get("code", "")).strip().upper()
    subtotal = request.args.get("subtotal", "0")
    try:
        subtotal = float(subtotal)
    except Exception:
        subtotal = 0.0
    if not uid or not code:
        return err_json("بيانات ناقصة")
    # تخمين أكواد الخصم: حد مشترك لكل IP فهاد المتجر + سقف للمتجر
    client_ip = request.remote_addr or ""
    if _any_shared_limited(("coupon_ip_store", f"{client_ip}|{uid}"), ("coupon_store", uid)):
        return err_json("محاولات كثيرة جداً — حاول بعد قليل", 429)

    c = _fb_get(f"data/{uid}/coupons/{code}")
    # نفس التحقق اللي يستعملو addOrder (services/coupons.py)
    problem = coupon_problem(c, subtotal)
    if problem:
        return err_json(problem, 404 if not isinstance(c, dict) or not c else 400)

    discount_amount = coupon_discount(c, subtotal)
    return ok_json({
        "code": code, "type": c.get("type", "percent"), "value": c.get("value", 0),
        "appliesTo": c.get("appliesTo", "all"),
        "discountAmount": round(discount_amount, 2),
    })
