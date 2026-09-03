from flask import Blueprint, request
# استوردي الدوال المشتركة الجاهزة من app.py بدل ما تعيدي كتابتها:
from app import require_auth, require_perm, _fb_get, _fb_put, _fb_delete, ok_json, err_json

discounts_bp = Blueprint("discounts", __name__)

# بنية القسيمة المقترحة:
# {code, type: "percent"|"fixed", value, minOrderTotal, maxUses, usedCount,
#  expiresAt, active, appliesTo: "all"|["productName1",...]}

@discounts_bp.route("/api/coupons/list", methods=["GET"])
@require_auth
@require_perm("store")
def list_coupons():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/coupons") or {})

@discounts_bp.route("/api/coupons/create", methods=["POST"])
@require_auth
@require_perm("store")
def create_coupon():
    # التحقق من صحة القيم + توليد/التحقق من عدم تكرار الكود
    ...

@discounts_bp.route("/api/coupons/validate", methods=["GET"])
def validate_coupon_public():
    # مسار عام (بدون توكن) — يُستدعى من صفحة المتجر العامة وقت الدفع
    # يتحقق: هل الكود موجود، فعّال، لم يتجاوز maxUses، لم تنتهِ صلاحيته
    ...