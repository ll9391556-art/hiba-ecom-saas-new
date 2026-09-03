from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

discounts_bp = Blueprint("discounts", __name__)

@discounts_bp.route("/api/coupons/list", methods=["GET"])
@require_auth
@require_perm("store")
def list_coupons():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/coupons") or {})