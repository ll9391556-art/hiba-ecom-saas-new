# -*- coding: utf-8 -*-
"""إعدادات البوت، المحادثات والرسائل، والإرسال للزبون. منقول من app.py بلا تغيير (Phase 4 / A7)."""
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

from core.config import (
    PLANS,
)
from core.db import (
    _fb_get,
    _fb_query,
)
from core.http import (
    _opt_float_arg,
    err_json,
    ok_json,
)
from core.security import (
    require_auth,
    require_perm,
)
from services.bot import (
    _log_conversation,
    send_facebook_message,
    send_whatsapp_message,
)
from services.users import (
    _sanitize_bot_settings_patch,
    _save_bot_settings,
    get_user_plan,
)

bp = Blueprint("messaging", __name__)




# ── Bot Settings ──────────────────────────────────────────
@bp.route("/api/getBotSettings", methods=["GET"])
@require_auth
@require_perm("bot")
def api_get_bot_settings():
    username = request.auth_username
    data = _fb_get(f"users/{username}") or {}
    safe = {k: v for k, v in data.items() if k != "Password"}
    return ok_json(safe)


@bp.route("/api/updateBotSettings", methods=["POST"])
@require_auth
@require_perm("bot")
def api_update_bot_settings():
    body     = request.get_json(silent=True) or {}
    uid      = request.auth_uid
    username = request.auth_username
    d        = body.get("data") or {}
    if not username: return err_json("Missing fields")
    # حماية Mass Assignment: نستثني الحقول الحساسة (plan/source/Password/User_ID/Username)
    # قبل الدمج — هذا المسار مخصص فقط لإعدادات البوت وليس لبيانات الحساب/الخطة.
    d = _sanitize_bot_settings_patch(d)
    return _save_bot_settings(username, uid, d)


# ── Conversations / Messages ───────────────────────────────
@bp.route("/api/getConversations", methods=["GET"])
@require_auth
@require_perm("messages")
def api_get_conversations():
    """قبل: كل conversations_meta/{uid} فكل نداء (الواجهة كل 10 ثواني). دابا (lastTimestamp مفهرس):
    - بلا معاملات: آخر `limit` محادثة (افتراضياً 50).
    - before=<lastTimestamp>: الصفحة الأقدم.
    - since=<cursor>: غير المحادثات اللي تحرّكت (reset=true إذا كثار بزاف).
    data الأحدث أولاً، مع cursor (وقت السيرفر بالثواني ناقص 30) وhasMore."""
    uid = request.auth_uid
    path = f"conversations_meta/{uid}"
    try:
        limit  = max(1, min(int(request.args.get("limit") or 50), 200))
        since  = _opt_float_arg("since")
        before = _opt_float_arg("before")
    except ValueError:
        return err_json("Invalid paging parameters")
    started = time.time()
    if since is not None:
        cap, found = 200, _fb_query(path, "lastTimestamp", start_at=since, limit_last=201)
    else:
        cap = limit
        found = _fb_query(path, "lastTimestamp", end_at=before, limit_last=limit + 2)
    if found is None:
        return err_json("تعذّر تحميل المحادثات — حاول بعد قليل", 503)
    result = []
    for sender_id, m in found.items():
        if not isinstance(m, dict): continue
        if before is not None and (m.get("lastTimestamp") or 0) >= before: continue
        result.append({
            "senderId": sender_id, "platform": m.get("platform",""),
            "lastMessage": m.get("lastMessage",""), "lastTimestamp": m.get("lastTimestamp",0),
            "lastDirection": m.get("lastDirection",""), "name": m.get("name","") or sender_id,
        })
    has_more = len(result) > cap
    if has_more:
        result = result[-cap:]  # تصاعدي → نخلّيو الأحدث
    result.sort(key=lambda x: x.get("lastTimestamp",0) or 0, reverse=True)
    body = {"status": "ok", "data": result, "hasMore": has_more, "cursor": started - 30}
    if since is not None and has_more:
        body["reset"] = True
    return jsonify(body)


@bp.route("/api/getConversationMessages", methods=["GET"])
@require_auth
@require_perm("messages")
def api_get_conversation_messages():
    uid = request.auth_uid
    sender_id = request.args.get("senderId","").strip()
    if not sender_id: return err_json("Missing senderId")
    # مفاتيح push مرتّبة زمنياً → order_by_key بلا فهرس. after/before = مفتاح رسالة
    try:
        limit = max(1, min(int(request.args.get("limit") or 100), 300))
    except ValueError:
        return err_json("Invalid paging parameters")
    after  = request.args.get("after", "").strip() or None
    before = request.args.get("before", "").strip() or None
    path = f"conversations/{uid}/{sender_id}"
    if after:
        found = _fb_query(path, "$key", start_at=after, limit_last=301)
    else:
        found = _fb_query(path, "$key", end_at=before, limit_last=limit + 2)
    if found is None:
        return err_json("تعذّر تحميل الرسائل — حاول بعد قليل", 503)
    items = []
    for k, v in found.items():
        if k in (after, before) or not isinstance(v, dict):
            continue
        row = dict(v); row["id"] = k
        items.append(row)
    has_more = False
    if not after and len(items) > limit:
        items, has_more = items[-limit:], True
    return jsonify({"status": "ok", "data": items, "hasMore": has_more})


@bp.route("/api/sendMessage", methods=["POST"])
@require_auth
@require_perm("messages")
def api_send_message():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    sender_id = str(body.get("senderId") or "").strip()
    text      = str(body.get("text") or "").strip()
    if not sender_id or not text:
        return err_json("Missing fields")
    if not PLANS.get(get_user_plan(uid), {}).get("bot", False):
        return err_json("هذه الميزة تتطلب خطة Pro أو أعلى", 403)
    meta = _fb_get(f"conversations_meta/{uid}/{sender_id}") or {}
    platform = meta.get("platform","fb")
    page_id  = meta.get("pageId","")
    if not meta:
        return err_json("لا توجد محادثة سابقة مع هذا العميل — لا يمكن بدء محادثة جديدة بسبب قيود ميتا", 404)
    bot_settings = _fb_get(f"users/{request.auth_username}") or {}
    ok = False
    if platform == "wa":
        token = str(bot_settings.get("whtsapp_token") or "").strip()
        phone_number_id = page_id or str(bot_settings.get("phone_number_id") or "").strip()
        if not token or not phone_number_id:
            return err_json("إعدادات واتساب غير مكتملة")
        ok = send_whatsapp_message(phone_number_id, sender_id, text, token)
    elif platform == "ig":
        token  = str(bot_settings.get("instgram_access_token") or "").strip()
        fb_pid = page_id or str(bot_settings.get("page_id_FB") or "").strip()
        if not token:
            return err_json("إعدادات إنستغرام غير مكتملة")
        ok = send_facebook_message(sender_id, text, token, page_id=(fb_pid or None))
    else:
        token  = str(bot_settings.get("fb_access_token") or "").strip()
        fb_pid = page_id or str(bot_settings.get("page_id_FB") or "").strip()
        if not token:
            return err_json("إعدادات فيسبوك غير مكتملة")
        ok = send_facebook_message(sender_id, text, token, page_id=(fb_pid or None))
    if not ok:
        return err_json("فشل إرسال الرسالة — تحقق من اتصال Facebook/Instagram/WhatsApp", 502)
    _log_conversation(uid, sender_id, "out", text, platform, via="manual", page_id=page_id)
    return ok_json(True)
