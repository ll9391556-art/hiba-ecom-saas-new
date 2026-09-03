from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

tracking_bp = Blueprint("tracking", __name__)

@tracking_bp.route("/api/tracking/list", methods=["GET"])
@require_auth
def list_tracking():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/tracking") or {})