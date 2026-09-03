from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_put, ok_json

multistore_bp = Blueprint("multistore", __name__)

@multistore_bp.route("/api/multistore/list", methods=["GET"])
@require_auth
def list_stores():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/stores") or {})