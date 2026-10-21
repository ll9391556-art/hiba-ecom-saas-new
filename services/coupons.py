# -*- coding: utf-8 -*-
"""الكوبونات: منطق تحقق واحد للمتجر العام (/api/coupons/validate) ولـ addOrder.
قبل Phase 4 كانو نسختين متطابقتين تقريباً (app.py وfeatures/discounts_api.py)."""
import logging
import time

from core.db import _fb_get, _fb_patch, _firebase_ref
from services.users import planHas_server

COUPONS_NOT_IN_PLAN = "أكواد الخصم متاحة من باقة Pro وفوق"

def coupon_problem(c, subtotal):
    """None إذا الكوبون صالح لهاد المجموع، وإلا رسالة السبب (نفس رسائل المتجر العام)."""
    if not c or not isinstance(c, dict):
        return "كود الخصم غير موجود"
    if not c.get("active", True):
        return "كود الخصم غير فعّال حالياً"
    if c.get("expiresAt"):
        try:
            if time.strftime("%Y-%m-%d") > str(c["expiresAt"])[:10]:
                return "انتهت صلاحية كود الخصم"
        except Exception:
            pass
    max_uses = int(c.get("maxUses", 0) or 0)
    used = int(c.get("usedCount", 0) or 0)
    if max_uses and used >= max_uses:
        return "تم استنفاد هذا الكود بالكامل"
    min_total = float(c.get("minOrderTotal", 0) or 0)
    if subtotal < min_total:
        return f"الحد الأدنى للطلب لاستعمال هذا الكود هو {min_total}"
    return None


def coupon_discount(c, subtotal):
    """قيمة الخصم (بلا تقريب): نسبة من المجموع، أو قيمة ثابتة ما تفوتش المجموع."""
    ctype = c.get("type", "percent")
    value = float(c.get("value", 0) or 0)
    return (subtotal * value / 100.0) if ctype == "percent" else min(value, subtotal)


def _validate_and_apply_coupon(uid, code, subtotal):
    """يعيد حساب الخصم من قاعدة الكوبونات على السيرفر — لا يثق بأي رقم قادم من الزبون.
    يرجّع (discount_amount, coupon_code_or_None). عند أي مشكلة يرجّع (0, None) بصمت
    (الطلب يستمر بلا خصم بدل ما يفشل بالكامل بسبب كود خصم غير صالح)."""
    code = str(code or "").strip().upper()
    if not code:
        return 0.0, None
    if not planHas_server(uid, "coupons"):  # كوبونات قديمة عند باقة بلا coupons: بلا خصم
        return 0.0, None
    c = _fb_get(f"data/{uid}/coupons/{code}")
    if coupon_problem(c, subtotal):
        return 0.0, None
    return round(max(0.0, coupon_discount(c, subtotal)), 2), code


def _increment_coupon_usage(uid, code):
    try:
        c = _fb_get(f"data/{uid}/coupons/{code}") or {}
        new_used = int(c.get("usedCount", 0) or 0) + 1
        _fb_patch(f"data/{uid}/coupons/{code}", {"usedCount": new_used})
    except Exception as e:
        logging.error(f"_increment_coupon_usage: {e}")
