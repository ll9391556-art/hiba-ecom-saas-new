# -*- coding: utf-8 -*-
"""لوحة الإدارة (/admin) ومسارات X-Admin-Key: الخطط، إنشاء العملاء، التعبئة (rebuildIndexes)، اللائحة. منقول من app.py بلا تغيير (Phase 4 / A8)."""
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
    EARLY_MAX_SLOTS,
    LIFETIME_MAX_SLOTS,
    PLANS,
    normalize_plan,
)
from core.db import (
    _fb_get,
    _fb_keys,
    _fb_put,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _hash_password,
    require_admin,
)
from services.bot import (
    _migrate_bot_logs,
)
from services.orders import (
    _rebuild_order_fields,
    _recompute_aggregates,
)
from services.users import (
    _LifetimeFull,
    _adjust_lifetime_counter,
    _rebuild_user_indexes,
    _plan_status,
    _slot_counter,
    _uname_key,
    _username_taken,
)

from core.templates import render
bp = Blueprint("admin", __name__)

# مدة الاشتراك اللي يحطّها الأدمين عند التفعيل (الدفع يدوي). بلا duration = ما تنتهيش
# (كيما قبل)، إلا early: عام دايماً. free ما عندهاش انتهاء.
_DURATIONS = {"month": ("monthly", 30), "year": ("yearly", 365), "none": (None, 0)}
_DAY_MS = 86_400_000


def _apply_duration(rec, old_plan, plan, duration):
    """يبدّل plan_period/plan_expires_at فـ rec. تجديد نفس الباقة قبل الانتهاء يزيد على الانتهاء الحالي."""
    duration = str(duration or "").strip().lower() or ("year" if plan == "early" else "none")
    if duration not in _DURATIONS:
        return False
    period, days = _DURATIONS[duration]
    if plan == "free" or not period:
        rec.pop("plan_period", None); rec.pop("plan_expires_at", None)
        return True
    now = int(time.time() * 1000)
    current = _plan_status(rec, now)[1].get("expiresAt", 0)
    base = current if (old_plan == plan and current > now) else now
    rec["plan_period"], rec["plan_expires_at"] = period, base + days * _DAY_MS
    return True

_LIFETIME_RETIRED = "باقة Lifetime ما بقاتش للبيع — المشتركين الحاليين فيها يبقاو، والجدد يختارو باقة أخرى"




@bp.route("/admin", methods=["GET"])
def admin_page():
    return render("admin.html"), 200


@bp.route("/api/updateUserPlan", methods=["POST"])
@require_admin
def api_update_user_plan():
    body     = request.get_json(silent=True) or {}
    uid      = str(body.get("userId")   or "").strip()
    username = str(body.get("username") or "").strip()
    plan     = normalize_plan(body.get("plan"))
    if not uid or not username: return err_json("Missing fields")
    if plan not in PLANS: return err_json(f"Invalid plan: {list(PLANS.keys())}")
    existing = _fb_get(f"users/{username}") or {}
    # عدّادات الباقات المحدودة (lifetime/full، early) تتبع الانتقال من/إلى الباقة
    # (lifetime↔full ما يبدّلوش). الدخول لـ early يحجز خانة قبل الكتابة، والحد يترفض.
    old_slot, new_slot = _slot_counter(existing.get("plan")), _slot_counter(plan)
    # lifetime/full ما بقاتش للبيع: غير اللي عندهم من قبل يبقاو (حتى lifetime↔full)
    if new_slot == "lifetimeAccounts" and old_slot != new_slot:
        return err_json(_LIFETIME_RETIRED)
    if new_slot == "earlyAccounts" and old_slot != new_slot:
        try:
            _adjust_lifetime_counter(1, cap=EARLY_MAX_SLOTS, counter="earlyAccounts")
        except _LifetimeFull:
            return err_json(f"تم الوصول للحد الأقصى ({EARLY_MAX_SLOTS}) من عرض أوائل التجار", 409)
        except Exception as e:
            logging.error(f"early counter reserve failed: {type(e).__name__}")
            return err_json("Firebase unavailable", 503)
    old_plan = normalize_plan(existing.get("plan"))
    if not _apply_duration(existing, old_plan, plan, body.get("duration")):
        if new_slot == "earlyAccounts" and old_slot != new_slot:
            try: _adjust_lifetime_counter(-1, counter="earlyAccounts")
            except Exception: pass
        return err_json("مدة غير صحيحة: month أو year أو none")
    existing["plan"]         = plan
    existing["plan_updated"] = time.strftime("%Y-%m-%d %H:%M")
    if not _fb_put(f"users/{username}", existing):
        if new_slot == "earlyAccounts" and old_slot != new_slot:
            try: _adjust_lifetime_counter(-1, counter="earlyAccounts")
            except Exception: pass
        return err_json("Firebase unavailable", 503)
    if old_slot != new_slot:
        moves = [(old_slot, -1)] + ([] if new_slot == "earlyAccounts" else [(new_slot, 1)])
        for counter, delta in moves:
            if not counter: continue
            try:
                _adjust_lifetime_counter(delta, counter=counter)
            except Exception as e:
                logging.error(f"{counter} update failed: {type(e).__name__} — شغّل rebuildIndexes")
    return ok_json({"plan": plan})


@bp.route("/api/admin/createClient", methods=["POST"])
@require_admin
def api_admin_create_client():
    body     = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    store_name = str(body.get("storeName") or "").strip() or "متجري"
    plan     = normalize_plan(body.get("plan"))
    source   = str(body.get("source") or "local").strip().lower()
    if source not in ("local", "fiverr"): source = "local"
    if not username or not password: return err_json("اسم المستخدم وكلمة السر مطلوبين")
    if len(password) < 6: return err_json("كلمة السر قصيرة جداً (6 أحرف على الأقل)")
    if plan not in PLANS: return err_json(f"خطة غير صحيحة: {list(PLANS.keys())}")
    if _slot_counter(plan) == "lifetimeAccounts": return err_json(_LIFETIME_RETIRED)
    record = {}
    if not _apply_duration(record, None, plan, body.get("duration")):
        return err_json("مدة غير صحيحة: month أو year أو none")
    if _username_taken(username): return err_json("اسم المستخدم مستعمل من قبل", 409)
    slot = _slot_counter(plan)
    if slot:
        # حجز خانة (lifetime أو early) ذرّياً قبل إنشاء الحساب (بدل عدّ /users كاملة)
        cap, label = (LIFETIME_MAX_SLOTS, "Lifetime") if slot == "lifetimeAccounts" else (EARLY_MAX_SLOTS, "أوائل التجار")
        try:
            _adjust_lifetime_counter(1, cap=cap, counter=slot)
        except _LifetimeFull:
            return err_json(f"تم الوصول للحد الأقصى ({cap}) من عروض {label}", 409)
        except Exception as e:
            logging.error(f"{slot} counter reserve failed: {type(e).__name__}")
            return err_json("Firebase unavailable", 503)
    new_uid = str(int(time.time() * 1000))
    if not _fb_put(f"users/{username}", {
        "Username": username, "Password": _hash_password(password),
        "User_ID": new_uid, "plan": plan, "source": source,
        "plan_updated": time.strftime("%Y-%m-%d %H:%M"), **record,
    }):
        if slot:
            try: _adjust_lifetime_counter(-1, counter=slot)
            except Exception: pass
        return err_json("Firebase unavailable", 503)
    _fb_put(f"uid_index/{new_uid}", username)
    _fb_put(f"uname_index/{_uname_key(username)}", username)
    _fb_put(f"data/{new_uid}/storeSettings", {
        "name": store_name, "tagline": "", "logo": "🛒", "lang": "AR", "currency": "DZD",
    })
    return ok_json({"username": username, "userId": new_uid,
                     "storeLink": f"{request.url_root.rstrip('/')}/?store={new_uid}"})


@bp.route("/api/admin/rebuildIndexes", methods=["POST"])
@require_admin
def api_admin_rebuild_indexes():
    """تعبئة لمرة وحدة بعد كل deploy يزيد فهرس (idempotent — تقدر تعاودها):
    - orders: createdAt/updatedAt/phoneDigits للطلبات القديمة.
    - users: uname_index، uid_index، team_uname_index، channel_index، وعدّاد lifetime.
    هادي الوحيدة (مع listClients) اللي تقرا /users و/team_users كاملة — بالقصد، مرة وحدة."""
    users_res = _rebuild_user_indexes()
    if users_res is None:
        return err_json("Firebase unavailable", 503)
    orders_res = _rebuild_order_fields()
    if isinstance(orders_res, tuple):
        return orders_res
    # المجاميع الجارية (stats/customers) لكل تاجر — من بعد حقول الطلبات
    agg_ok, agg_failed = 0, []
    for uid in (_fb_keys("data") or []):
        if _recompute_aggregates(uid) is None:
            agg_failed.append(uid)
        else:
            agg_ok += 1
    logs_res = _migrate_bot_logs()
    if logs_res is None:
        return err_json("Firebase unavailable", 503)
    return ok_json({"orders": orders_res, "users": users_res,
                    "aggregates": {"merchants": agg_ok, "failed": agg_failed}, "botLogs": logs_res})


@bp.route("/api/admin/listClients", methods=["GET"])
@require_admin
def api_admin_list_clients():
    users = _fb_get("users") or {}
    result = []
    for uname, u in users.items():
        if isinstance(u, dict):
            result.append({
                "username": u.get("Username", uname), "userId": u.get("User_ID", ""),
                "plan": normalize_plan(u.get("plan")), "planUpdated": u.get("plan_updated", ""),
                "planPeriod": u.get("plan_period", ""), "planExpiresAt": u.get("plan_expires_at", 0),
                "planState": _plan_status(u)[1]["state"],
                "source": u.get("source", "local"),
            })
    result.sort(key=lambda x: x.get("planUpdated",""), reverse=True)
    return ok_json(result)
