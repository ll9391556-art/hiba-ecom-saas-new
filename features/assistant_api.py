from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

assistant_bp = Blueprint("assistant", __name__)

@assistant_bp.route("/api/assistant/settings", methods=["GET"])
@require_auth
def get_assistant():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/assistant") or {})