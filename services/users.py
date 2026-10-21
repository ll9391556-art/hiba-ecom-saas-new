# -*- coding: utf-8 -*-
"""الحسابات: سجل المستخدم والخطة، الاستهلاك الشهري، فهارس الأسماء (uname/team/uid)، عدّاد
lifetime، حفظ إعدادات البوت مع channel_index، وكاش إعدادات القنوات.
منقول من app.py بلا تغيير (Phase 4 / A4). app.py يعاود يصدّر نفس الأسماء."""
import logging
import threading
import time

from core.config import PLANS
from core.db import _fb_delete, _fb_get, _fb_keys, _fb_patch, _fb_put, _firebase_ref
from core.http import err_json, ok_json

_settings_cache: dict = {}


_settings_cache_lock  = threading.Lock()


_CACHE_TTL            = 120


_NEG_CACHE_TTL        = 30   # قناة مجهولة (ما عندها channel_index) — كاش قصير


def _count_team_members(owner_uid):
    try:
        raw = _fb_get(f"data/{owner_uid}/teamMembers") or {}
        return len([1 for v in raw.values() if isinstance(v, dict)])
    except Exception:
        return 0


# ── تتبع الاستهلاك الشهري ──────────────────────────────────
def _usage_month_key():
    return time.strftime("%Y-%m")


def _get_usage(uid, field):
    val = _fb_get(f"data/{uid}/usage/{_usage_month_key()}/{field}") or 0
    try: return int(val)
    except Exception: return 0


def _increment_usage(uid, field):
    path = f"data/{uid}/usage/{_usage_month_key()}/{field}"
    try:
        ref = _firebase_ref(path)
        new_val = ref.transaction(lambda current: (current or 0) + 1)
        return new_val if isinstance(new_val, int) else _get_usage(uid, field)
    except Exception as e:
        logging.error(f"_increment_usage transaction failed, fallback: {e}")
        new_val = _get_usage(uid, field) + 1
        _fb_put(path, new_val)
        return new_val


def _plan_cap(uid, cap_field):
    plan = get_user_plan(uid)
    return PLANS.get(plan, {}).get(cap_field)


def _under_cap(uid, usage_field, cap_field):
    cap = _plan_cap(uid, cap_field)
    if not cap: return True
    return _get_usage(uid, usage_field) < cap


def _get_user_record(uid):
    """uid → users/{username} عبر uid_index فقط. قبل: كان يقرا /users كاملة كي يغيب الفهرس —
    ومسار عام (addOrder بـ userId عشوائي) كان يقدر يفرض هاد التنزيل. الحسابات القديمة بلا فهرس
    تتصلّح بـ /api/admin/rebuildIndexes."""
    try:
        uname = _fb_get(f"uid_index/{uid}")
        if uname:
            rec = _fb_get(f"users/{uname}")
            if isinstance(rec, dict) and str(rec.get("User_ID", "")) == str(uid):
                return rec
    except Exception:
        pass
    return {}


def get_user_plan(uid):
    return str(_get_user_record(uid).get("plan", "starter")).lower()


# ── فهارس الأسماء وعدّاد lifetime (بدل قراءة /users و/team_users كاملة) ──
# uname_index/{lower} → مفتاح users، team_uname_index/{lower} → مفتاح team_users.
# counters/lifetimeAccounts يتحدّث بـ transaction مع كل تغيير خطة من/إلى lifetime/full.
_LIFETIME_PLANS = ("lifetime", "full")


def _uname_key(username):
    return str(username or "").strip().lower()


def _username_taken(username):
    """اسم مستعمل (بلا اعتبار الحروف الكبيرة) عند صاحب حساب أو عضو فريق؟"""
    key = _uname_key(username)
    return bool(_fb_get(f"uname_index/{key}") or _fb_get(f"team_uname_index/{key}")
                or _fb_get(f"users/{username}") or _fb_get(f"team_users/{username}"))


_EARLY_PLANS = ("early",)


def _slot_counter(plan):
    """الباقات المحدودة العدد: lifetime/full (قديمة) وearly (أوائل التجار) — كل وحدة بعدّادها."""
    plan = str(plan or "").lower()
    if plan in _LIFETIME_PLANS: return "lifetimeAccounts"
    if plan in _EARLY_PLANS:    return "earlyAccounts"
    return None


def _count_lifetime_accounts(counter="lifetimeAccounts"):
    try:
        return max(0, int(_fb_get(f"counters/{counter}") or 0))
    except Exception:
        return 0


class _LifetimeFull(Exception):
    pass


def _adjust_lifetime_counter(delta, cap=None, counter="lifetimeAccounts"):
    """+1/-1 ذرّياً. مع cap: يرمي _LifetimeFull إذا الحد وصل (بلا كتابة)."""
    def _txn(cur):
        cur = max(0, int(cur or 0))
        if cap is not None and delta > 0 and cur + delta > cap:
            raise _LifetimeFull()
        return max(0, cur + delta)
    _firebase_ref(f"counters/{counter}").transaction(_txn)


# ── حماية حقول حساب المستخدم من التعديل الذاتي (Mass Assignment) ─────
# قبل: /api/updateBotSettings و /api/saas (action=updateBotSettings) كانا يدمجان
# كائن "data"/"payload" القادم كاملاً من جسم الطلب مباشرة داخل عقدة users/{username} —
# وهي نفس العقدة التي تخزّن plan/source/Password/User_ID. أي مستخدم مسجّل (حتى بخطة
# Free) كان يقدر يبعث {"data":{"plan":"lifetime"}} ويرقّي نفسه مجاناً، أو يبدّل
# Username/User_ID/Password عبره. الآن: whitelist صارم يستثني كل الحقول الحساسة قبل
# أي دمج مع سجل المستخدم — هذه المسارات مخصصة فقط لإعدادات البوت (Gemini key,
# AI instructions, tokens الخ) وليس لبيانات الحساب/الخطة.
_PROTECTED_USER_FIELDS = {
    "plan", "source", "Password", "User_ID", "Username",
    "plan_updated",
}


def _sanitize_bot_settings_patch(d):
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if k not in _PROTECTED_USER_FIELDS}


def planHas_server(uid, feature):
    plan = get_user_plan(uid)
    return bool(PLANS.get(plan, {}).get(feature, False))


# معرّفات القنوات فـ users/{username}: كل وحدة عندها channel_index/{id} → username، باش
# webhook يلقى التاجر بقراءتين بلا مسح /users. SEC-009: معرّف مربوط بحساب آخر يترفض.
_CHANNEL_FIELDS = ("page_id_FB", "Page_ID_instgram", "page_id_instagram", "phone_number_id")


def _channel_ids(rec):
    return {str(rec.get(f) or "").strip() for f in _CHANNEL_FIELDS} - {""}


def _save_bot_settings(username, uid, patch):
    existing = _fb_get(f"users/{username}") or {}
    updated  = {**existing, **patch, "Username": username, "User_ID": uid}
    old_ids, new_ids = _channel_ids(existing), _channel_ids(updated)
    for cid in new_ids:
        if not cid.isdigit():
            return err_json(f"معرّف غير صالح: {cid} — أرقام فقط")
    for cid in new_ids - old_ids:
        owner = _fb_get(f"channel_index/{cid}")
        if owner and owner != username:
            return err_json(f"المعرّف {cid} مربوط بحساب آخر", 409)
    if not _fb_put(f"users/{username}", updated):
        return err_json("Firebase unavailable", 503)
    for cid in new_ids:
        _fb_put(f"channel_index/{cid}", username)
    for cid in old_ids - new_ids:
        if _fb_get(f"channel_index/{cid}") == username:
            _fb_delete(f"channel_index/{cid}")
    with _settings_cache_lock:
        _settings_cache.clear()
    return ok_json(True)


def _rebuild_user_indexes():
    # _fb_get يرجّع None للـ "ما كاينش" وللخطأ معاً — نتأكدو أولاً أن Firebase يجاوب
    if _fb_keys("/") is None:
        return None
    as_dict = lambda v: v if isinstance(v, dict) else {}
    users, members = as_dict(_fb_get("users")), as_dict(_fb_get("team_users"))
    existing_channels = as_dict(_fb_get("channel_index"))
    patch, conflicts, unames, claims = {}, [], {}, {}
    lifetime = early = 0
    for key, u in users.items():
        if not isinstance(u, dict):
            continue
        lower = _uname_key(u.get("Username") or key)
        if lower in unames:
            conflicts.append(f"uname_index/{lower}: {unames[lower]} vs {key}")
        else:
            unames[lower] = key
            patch[f"uname_index/{lower}"] = key
        if u.get("User_ID"):
            patch[f"uid_index/{u['User_ID']}"] = key
        slot = _slot_counter(u.get("plan"))
        lifetime += slot == "lifetimeAccounts"
        early += slot == "earlyAccounts"
        for cid in _channel_ids(u):
            if cid.isdigit():
                claims.setdefault(cid, []).append(key)
    for cid, claimants in claims.items():
        current = existing_channels.get(cid)
        owner = current if current in claimants else claimants[0]
        patch[f"channel_index/{cid}"] = owner
        conflicts += [f"channel_index/{cid}: {owner} vs {other}" for other in claimants if other != owner]
    for key, m in members.items():
        if not isinstance(m, dict):
            continue
        lower = _uname_key(m.get("Username") or key)
        if lower in unames:
            conflicts.append(f"team_uname_index/{lower}: owner {unames[lower]} vs member {key}")
        patch[f"team_uname_index/{lower}"] = key
    patch["counters/lifetimeAccounts"] = lifetime
    patch["counters/earlyAccounts"] = early
    if not _fb_patch("/", patch):
        return None
    if conflicts:
        logging.warning(f"🔧 rebuildIndexes: {len(conflicts)} conflicts — راجعهم يدوياً")
    return {"users": len(unames), "members": len(members), "lifetimeAccounts": lifetime,
            "earlyAccounts": early, "conflicts": conflicts}
