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
    ok_json, err_json,
)

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

    c = _fb_get(f"data/{uid}/coupons/{code}")
    if not c or not isinstance(c, dict):
        return err_json("كود الخصم غير موجود", 404)
    if not c.get("active", True):
        return err_json("كود الخصم غير فعّال حالياً")
    if c.get("expiresAt"):
        try:
            if time.strftime("%Y-%m-%d") > str(c["expiresAt"])[:10]:
                return err_json("انتهت صلاحية كود الخصم")
        except Exception:
            pass
    max_uses = int(c.get("maxUses", 0) or 0)
    used = int(c.get("usedCount", 0) or 0)
    if max_uses and used >= max_uses:
        return err_json("تم استنفاد هذا الكود بالكامل")
    min_total = float(c.get("minOrderTotal", 0) or 0)
    if subtotal < min_total:
        return err_json(f"الحد الأدنى للطلب لاستعمال هذا الكود هو {min_total}")

    discount_amount = (subtotal * c["value"] / 100.0) if c["type"] == "percent" else min(c["value"], subtotal)
    return ok_json({
        "code": code, "type": c["type"], "value": c["value"],
        "appliesTo": c.get("appliesTo", "all"),
        "discountAmount": round(discount_amount, 2),
    })


@discounts_bp.route("/api/coupons/redeem", methods=["POST"])
def redeem_coupon_public():
    """
    مسار عام يُستدعى بعد إرسال الطلب بنجاح عشان يزيد usedCount بـ 1.
    ملاحظة: ده حل بسيط (best-effort) — عميل خبيث نظرياً يقدر يستدعيه بلا ما يعمل
    طلب فعلي. لو بدك ضبط 100%، الحل الأدق هو إلحاق التحقق والزيادة داخل
    /api/addOrder نفسها بالملف الأصلي (تعديل صغير موضّح بالخطة).
    """
    body = request.get_json(silent=True) or {}
    uid = str(body.get("userId") or "").strip()
    code = str(body.get("code") or "").strip().upper()
    if not uid or not code:
        return err_json("بيانات ناقصة")
    c = _fb_get(f"data/{uid}/coupons/{code}")
    if not c:
        return err_json("غير موجود", 404)
    new_used = int(c.get("usedCount", 0) or 0) + 1
    _fb_patch(f"data/{uid}/coupons/{code}", {"usedCount": new_used})
    return ok_json(True)