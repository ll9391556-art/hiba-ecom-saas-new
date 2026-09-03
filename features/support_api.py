from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

support_bp = Blueprint("support", __name__)

@support_bp.route("/api/support/tickets", methods=["GET"])
@require_auth
def list_tickets():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/support") or {})