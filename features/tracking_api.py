# -*- coding: utf-8 -*-
"""
موديول أدوات التتبع الإعلاني — Meta / TikTok / Google Ads / Snapchat Pixels
قاعدة البيانات: data/{uid}/trackingSettings
"""
import re
from flask import Blueprint, request
from app import require_auth, require_perm, _fb_get, _fb_patch, ok_json, err_json

tracking_bp = Blueprint("tracking", __name__)

_ALLOWED_FIELDS = {
    "metaPixelId": r"^\d{10,20}$",
    "tiktokPixelId": r"^[A-Za-z0-9]{10,30}$",
    "googleAdsId": r"^AW-\d{6,15}$",
    "googleAnalyticsId": r"^G-[A-Za-z0-9]{6,12}$",
    "snapPixelId": r"^[A-Za-z0-9-]{10,40}$",
}


@tracking_bp.route("/api/tracking/getSettings", methods=["GET"])
@require_auth
@require_perm("store")
def get_tracking_settings():
    uid = request.auth_uid
    return ok_json(_fb_get(f"data/{uid}/trackingSettings") or {})


@tracking_bp.route("/api/tracking/save", methods=["POST"])
@require_auth
@require_perm("store")
def save_tracking_settings():
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    patch = {}
    for field, pattern in _ALLOWED_FIELDS.items():
        if field not in body:
            continue
        val = str(body.get(field) or "").strip()
        if not val:
            patch[field] = ""          # سماح بمسح القيمة
            continue
        if not re.match(pattern, val):
            return err_json(f"قيمة {field} غير صالحة")
        patch[field] = val
    if patch:
        _fb_patch(f"data/{uid}/trackingSettings", patch)
    return ok_json(True)


@tracking_bp.route("/api/tracking/public", methods=["GET"])
def get_public_tracking():
    """مسار عام (بلا توكن) — تستدعيه صفحة المتجر العامة لتحميل الـ pixels."""
    uid = request.args.get("userId", "").strip()
    if not uid:
        return err_json("Missing userId")
    data = _fb_get(f"data/{uid}/trackingSettings") or {}
    return ok_json({k: v for k, v in data.items() if v})