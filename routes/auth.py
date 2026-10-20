# -*- coding: utf-8 -*-
"""تسجيل الدخول، هوية الجلسة (/api/me)، وفريق العمل. منقول من app.py بلا تغيير (Phase 4 / A7)."""
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

from core.audit import (
    log_audit_entry,
)
from core.config import (
    MAX_TEAM_MEMBERS,
)
from core.db import (
    _fb_delete,
    _fb_get,
    _fb_patch,
    _fb_put,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _any_shared_limited,
    _clean_perms,
    _hash_password,
    _is_bcrypt_hash,
    _login_rate_limited,
    _verify_password,
    issue_token,
    require_auth,
    require_owner,
)
from services.users import (
    _count_team_members,
    _uname_key,
    _username_taken,
    planHas_server,
)

bp = Blueprint("auth", __name__)




# ── Auth ──────────────────────────────────────────────────
@bp.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(silent=True) or {}
    user = str(body.get("username") or "").strip()
    pwd  = str(body.get("password") or "").strip()

    # Rate limiting ضد brute-force على كلمات السر — حسب IP + اسم المستخدم معاً.
    # request.remote_addr مُصحَّح الآن عبر ProxyFix بدل الوثوق بهيدر X-Forwarded-For الخام.
    client_ip = request.remote_addr or ""
    if _login_rate_limited(f"login:{client_ip}:{user.lower()}"):
        return err_json("محاولات دخول كثيرة جداً — حاول بعد 5 دقائق", 429)

    if not user or not pwd:
        return err_json("Missing credentials")
    # حد مشترك بين الـ workers: لكل IP، ولكل اسم مستخدم مهما كان الـ IP (password spraying)
    if _any_shared_limited(("login_ip", client_ip), ("login_user", user.lower())):
        return err_json("محاولات دخول كثيرة جداً — حاول بعد 10 دقائق", 429)

    # 1) نحاول أولاً كصاحب حساب رئيسي (owner) — users/{key} عبر uname_index (بلا اعتبار
    #    الحروف الكبيرة). قبل: قراءة /users كاملة (توكنات كل التجار) فكل تسجيل دخول.
    #    حساب قديم بلا فهرس: المفتاح بنفس الاسم بالضبط، حتى تتعدّى rebuildIndexes.
    owner_key = _fb_get(f"uname_index/{_uname_key(user)}") or user
    udata = _fb_get(f"users/{owner_key}")
    if isinstance(udata, dict) and str(udata.get("Username") or "").lower() == user.lower():
        stored_pw = str(udata.get("Password") or "")
        if not _verify_password(pwd, stored_pw):
            return err_json("Invalid credentials", 401)
        if not _is_bcrypt_hash(stored_pw):
            _fb_patch(f"users/{owner_key}", {"Password": _hash_password(pwd)})
        token = issue_token(udata.get("User_ID", ""), udata.get("Username", user), role="owner")
        safe  = {k: v for k, v in udata.items() if k != "Password"}
        safe["token"] = token
        safe["role"]  = "owner"
        return ok_json(safe)

    # 2) لم يُوجد كصاحب حساب — نحاول كعضو فريق — team_users/{key} عبر team_uname_index
    #    (قبل: قراءة /team_users كاملة كي ما يطابقش الاسم المفتاح بالضبط)
    member_key = _fb_get(f"team_uname_index/{_uname_key(user)}") or user
    member = _fb_get(f"team_users/{member_key}")
    if not isinstance(member, dict) or str(member.get("Username") or member_key).lower() != user.lower():
        member = None
    if member and isinstance(member, dict):
        stored_pw = str(member.get("Password") or "")
        if not _verify_password(pwd, stored_pw):
            return err_json("Invalid credentials", 401)
        if not member.get("active", True):
            return err_json("هذا الحساب معطّل حالياً — تواصل مع صاحب المتجر", 403)
        if not _is_bcrypt_hash(stored_pw):
            _fb_patch(f"team_users/{member_key}", {"Password": _hash_password(pwd)})
        perms = _clean_perms(member.get("permissions"))
        token = issue_token(member.get("ownerUid", ""), member.get("ownerUsername", ""),
                             role="member", perms=perms,
                             member_username=member_key, member_name=member.get("name", member_key))
        safe = {
            "Username":        member.get("ownerUsername", ""),
            "User_ID":         member.get("ownerUid", ""),
            "role":            "member",
            "memberUsername":  member_key,
            "memberName":      member.get("name", member_key),
            "permissions":     perms,
            "token":           token,
        }
        return ok_json(safe)

    return err_json("Invalid credentials", 401)


@bp.route("/api/me", methods=["GET"])
@require_auth
def api_me():
    """هوية الجلسة الحالية باش الواجهة تعاود تفتح اللوحة بعد reload من of_token — بلا أي سر
    (ماشي كيما /api/login اللي يرجّع سجل users كامل). require_auth يرفض التوكن المنتهي أو
    الغلط (401) والعضو المعطّل (403)، ويجيب صلاحيات العضو الحالية من قاعدة البيانات."""
    me = {"Username": request.auth_username, "User_ID": request.auth_uid, "role": request.auth_role}
    if request.auth_role == "member":
        me.update(memberUsername=request.auth_member_username,
                  memberName=request.auth_member_name, permissions=request.auth_perms)
    return ok_json(me)


# ── فريق العمل — Team Members (owner فقط) ──────────────────
@bp.route("/api/team/listMembers", methods=["GET"])
@require_auth
@require_owner
def api_team_list_members():
    uid = request.auth_uid
    raw = _fb_get(f"data/{uid}/teamMembers") or {}
    members = []
    if isinstance(raw, dict):
        for uname, m in raw.items():
            if isinstance(m, dict):
                members.append({
                    "username": uname, "name": m.get("name", uname),
                    "permissions": m.get("permissions", {}), "active": m.get("active", True),
                    "created_at": m.get("created_at", ""),
                })
    members.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return ok_json(members)


@bp.route("/api/team/addMember", methods=["POST"])
@require_auth
@require_owner
def api_team_add_member():
    body = request.get_json(silent=True) or {}
    uid            = request.auth_uid
    owner_username = request.auth_username
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    name     = str(body.get("name") or "").strip() or username
    perms    = _clean_perms(body.get("permissions"))
    if not username or not password:
        return err_json("اسم المستخدم وكلمة السر مطلوبين")
    if len(password) < 6:
        return err_json("كلمة السر قصيرة جداً (6 أحرف على الأقل)")
    if not planHas_server(uid, "team"):
        return err_json("ميزة الفريق غير متاحة لخطتك الحالية", 403)
    if _count_team_members(uid) >= MAX_TEAM_MEMBERS:
        return err_json(f"وصلت للحد الأقصى ({MAX_TEAM_MEMBERS}) من أعضاء الفريق", 409)
    if _username_taken(username):
        return err_json("اسم المستخدم مستعمل من قبل", 409)
    now = time.strftime("%Y-%m-%d %H:%M")
    record_public = {"name": name, "permissions": perms, "active": True, "created_at": now}
    record_login  = {
        "Username": username, "Password": _hash_password(password),
        "ownerUid": uid, "ownerUsername": owner_username,
        "name": name, "permissions": perms, "active": True, "created_at": now,
    }
    _fb_put(f"data/{uid}/teamMembers/{username}", record_public)
    _fb_put(f"team_users/{username}", record_login)
    _fb_put(f"team_uname_index/{_uname_key(username)}", username)
    return ok_json({"username": username})


@bp.route("/api/team/updateMember", methods=["POST"])
@require_auth
@require_owner
def api_team_update_member():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    username = str(body.get("username") or "").strip()
    if not username: return err_json("Missing username")
    existing = _fb_get(f"team_users/{username}")
    if not existing or str(existing.get("ownerUid", "")) != str(uid):
        return err_json("العضو غير موجود", 404)
    patch_public, patch_login = {}, {}
    if "name" in body:
        val = str(body.get("name") or "").strip() or username
        patch_public["name"] = patch_login["name"] = val
    if "permissions" in body:
        perms = _clean_perms(body.get("permissions"))
        patch_public["permissions"] = patch_login["permissions"] = perms
    if "active" in body:
        patch_public["active"] = patch_login["active"] = bool(body.get("active"))
    if body.get("password"):
        newpass = str(body.get("password")).strip()
        if len(newpass) < 6: return err_json("كلمة السر قصيرة جداً (6 أحرف على الأقل)")
        patch_login["Password"] = _hash_password(newpass)
    if patch_public: _fb_patch(f"data/{uid}/teamMembers/{username}", patch_public)
    if patch_login:  _fb_patch(f"team_users/{username}", patch_login)
    return ok_json(True)


@bp.route("/api/team/deleteMember", methods=["POST"])
@require_auth
@require_owner
def api_team_delete_member():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    username = str(body.get("username") or "").strip()
    if not username: return err_json("Missing username")
    existing = _fb_get(f"team_users/{username}")
    if not existing or str(existing.get("ownerUid", "")) != str(uid):
        return err_json("العضو غير موجود", 404)
    _fb_delete(f"data/{uid}/teamMembers/{username}")
    _fb_delete(f"team_users/{username}")
    if _fb_get(f"team_uname_index/{_uname_key(username)}") == username:
        _fb_delete(f"team_uname_index/{_uname_key(username)}")
    log_audit_entry(uid, request.auth_member_username or "owner", f"حذف عضو فريق {username}")
    return ok_json(True)
