# -*- coding: utf-8 -*-
"""/api/saas: وكيل Firebase محدود بـ _path_allowed + سجل البوت وإعدادات البوت. منقول من app.py بلا تغيير (Phase 4 / A8)."""
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from urllib.parse import quote, unquote

import requests
from flask import Blueprint, abort, jsonify, make_response, request, send_from_directory
from markupsafe import escape as _esc

from core.db import (
    _fb_get,
    _fb_patch,
    _fb_push,
    _fb_put,
    _fb_query,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _extract_bearer,
    decode_token,
)
from services.users import (
    _sanitize_bot_settings_patch,
    _save_bot_settings,
)

bp = Blueprint("saas", __name__)




@bp.route("/api/saas", methods=["POST","OPTIONS"])
def api_saas():
    if request.method == "OPTIONS": return jsonify({}), 200
    token   = _extract_bearer(request)
    auth    = decode_token(token) if token else None
    if not auth or not auth.get("uid"):
        return err_json("Unauthorized", 401)
    auth_uid      = auth["uid"]
    auth_username = auth.get("username", "")
    auth_role     = auth.get("role", "owner")
    auth_perms    = auth.get("perms", {}) or {}

    payload = request.get_json(silent=True) or {}
    action  = str(payload.get("action") or "").strip()
    if not action: return err_json("missing_action")
    def _path_allowed(path):
        # المقاطع الفارغة تتحذف كيما يدير Firebase — قبل: "data/{uid}//usage" كان يدوز
        # الفحص (SEC-010)، و"data/{uid}/" كان يسمح بالكتابة فوق شجرة التاجر كاملة.
        # orders/stats/customers/ratings ممنوعين: المجاميع الجارية تتحدّث غير من المسارات
        # المخصصة، وكتابة مباشرة كانت تخليهم غالطين.
        segs = [s for s in str(path or "").split("/") if s]
        blocked_segments = {"usage", "integrations", "landingPages", "teamMembers",
                            "orders", "stats", "customers", "ratings", "deletedOrders"}
        if len(segs) >= 3 and segs[0] == "data" and segs[1] == str(auth_uid):
            return segs[2] not in blocked_segments
        return len(segs) >= 2 and segs[0] == "ai_logs" and segs[1] == str(auth_uid)

    if action in ("firebaseGet", "firebaseSet", "firebaseUpdate", "firebasePush") and auth_role == "member":
        return err_json("غير مسموح لعضو الفريق باستعمال هذا المسار", 403)
    if action in ("getBotLogs", "updateBotSettings") and auth_role == "member" and not auth_perms.get("bot"):
        return err_json("ليس لديك صلاحية الوصول لهذا القسم", 403)

    try:
        if action == "firebaseGet":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            return ok_json(_fb_get(payload["path"]))
        if action == "firebaseSet":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            value = payload.get("payload", payload.get("data"))
            # firebase-admin يرفض set(None) — قبل، _fb_put كان يفشل بصمت والرد يقول ok
            if value is None: return err_json("set requires a value")
            if not _fb_put(payload["path"], value): return err_json("write failed", 500)
            return ok_json(True)
        if action == "firebaseUpdate":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            data = payload.get("payload", payload.get("data"))
            if not isinstance(data, dict): return err_json("update requires object")
            _fb_patch(payload["path"], data)
            return ok_json(True)
        if action == "firebasePush":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            return ok_json({"key": _fb_push(payload["path"], payload.get("payload", payload.get("data")))})
        if action == "getBotLogs":
            limit = max(1, min(int(payload.get("limit") or 200), 500))
            found = _fb_query(f"bot_logs/{auth_uid}", "timestamp", limit_last=limit)
            if found is None:
                return err_json("تعذّر تحميل السجل — حاول بعد قليل", 503)
            items = [dict(v, id=k) for k, v in found.items() if isinstance(v, dict)]
            items.sort(key=lambda x: x.get("timestamp", 0) or 0, reverse=True)
            return ok_json(items)
        if action == "updateBotSettings":
            if not auth_username: return err_json("missing_username")
            data = payload.get("payload", payload.get("data")) or {}
            data = _sanitize_bot_settings_patch(data)
            if not data:
                return ok_json(True)
            return _save_bot_settings(auth_username, auth_uid, data)
        return err_json("unknown_action")
    except Exception as e:
        logging.error(f"/api/saas: {e}")
        return err_json(str(e), 500)
