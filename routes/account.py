# -*- coding: utf-8 -*-
"""الخطة والاستهلاك (/api/getUserPlan) وإعادة حساب المجاميع (/api/recalcStats). منقول من app.py بلا تغيير (Phase 4 / A7)."""
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
    BOT_LAUNCHED,
    LIFETIME_MAX_SLOTS,
    PLANS,
)
from core.db import (
    _fb_get,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _login_rate_limited,
    require_auth,
    require_owner,
)
from services.orders import (
    _recompute_aggregates,
)
from services.users import (
    _count_lifetime_accounts,
    _count_team_members,
    _get_usage,
    _get_user_record,
)

bp = Blueprint("account", __name__)




# ── Plans / Subscriptions ─────────────────────────────────
@bp.route("/api/getUserPlan", methods=["GET"])
@require_auth
def api_get_user_plan():
    uid      = request.auth_uid
    user_rec = _get_user_record(uid)
    plan     = str(user_rec.get("plan", "starter")).lower()
    source   = str(user_rec.get("source", "local")).lower()
    currency = (_fb_get(f"data/{uid}/storeSettings/currency") or "DZD")
    plan_features = PLANS.get(plan, PLANS["starter"])
    usage = {}
    if plan_features.get("orderCap"):
        usage["orders"]  = {"used": _get_usage(uid, "orderCount"),  "cap": plan_features["orderCap"]}
    if plan_features.get("botMsgCap"):
        usage["botMsgs"] = {"used": _get_usage(uid, "botMsgCount"), "cap": plan_features["botMsgCap"]}
    lifetime_left = max(0, LIFETIME_MAX_SLOTS - _count_lifetime_accounts()) if source == "local" else None
    return ok_json({"plan": plan, "features": plan_features, "currency": currency,
                     "source": source, "lifetimeSlotsLeft": lifetime_left,
                     "botLaunched": BOT_LAUNCHED, "usage": usage,
                     "role": getattr(request, "auth_role", "owner"),
                     "teamCount": _count_team_members(uid)})


@bp.route("/api/recalcStats", methods=["POST"])
@require_auth
@require_owner
def api_recalc_stats():
    """إصلاح يدوي للمجاميع (إذا انقطع شي حاجة بين كتابة طلب وتحديث المجموع): حساب كامل
    من كل الطلبات. مرة فـ 10 دقائق لكل تاجر — قراءة كاملة غالية."""
    uid = request.auth_uid
    if _login_rate_limited(f"recalc:{uid}", max_attempts=1, window=600):
        return err_json("تمت إعادة الحساب مؤخراً — حاول بعد 10 دقائق", 429)
    res = _recompute_aggregates(uid)
    if res is None:
        return err_json("Firebase unavailable", 503)
    return ok_json(res)
