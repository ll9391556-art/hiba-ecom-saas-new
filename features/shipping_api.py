from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

shipping_bp = Blueprint("shipping", __name__)

@shipping_bp.route("/api/shipping/config", methods=["GET"])
@require_auth
def get_shipping():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/shipping") or {})