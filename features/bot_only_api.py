from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

bot_bp = Blueprint("bot", __name__)

@bot_bp.route("/api/bot-only/config", methods=["GET"])
@require_auth
def get_bot_only():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/bot_only") or {})