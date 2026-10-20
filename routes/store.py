# -*- coding: utf-8 -*-
"""إعدادات المتجر، تسيير صفحات الهبوط، ورفع الصور. منقول من app.py بلا تغيير (Phase 4 / A7)."""
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
from firebase_admin import storage as fb_storage
from markupsafe import escape as _esc

from core.config import (
    FB_STORAGE_BUCKET,
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
    require_auth,
    require_perm,
)
from services.landing import (
    _generate_landing_copy,
    _generate_landing_questions,
    _new_landing_id,
    _sanitize_image_url,
)
from services.users import (
    planHas_server,
)

bp = Blueprint("store", __name__)




_STORE_TEXT_LIMITS = {"name": 120, "tagline": 300, "logo": 32, "lang": 8}


_STORE_CURRENCIES  = ("DZD", "EUR", "USD")


def _clean_store_setting(field, value, current):
    """تحقق خفيف لإعدادات المتجر: نوع + طول فقط، بلا فلترة حروف (عربي/فرنسي/إيموجي يمرّو كما هم —
    الحماية من XSS بالتهريب وقت العرض). قيمة مطابقة للمخزّنة حالياً تتقبل دائماً باش المتاجر
    القديمة تقدر تعاود تحفظ."""
    if current is not None and value == current:
        return True, value
    if field == "logoImage":
        if value == "":
            return True, ""
        clean = _sanitize_image_url(value) if isinstance(value, str) else ""
        return (bool(clean), clean)
    if field == "currency":
        return (value in _STORE_CURRENCIES, value)
    if not isinstance(value, str) or len(value) > _STORE_TEXT_LIMITS[field]:
        return False, None
    return True, value


@bp.route("/api/updateStoreSettings", methods=["POST"])
@require_auth
@require_perm("store")
def api_update_store_settings():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    if not isinstance(d, dict): return err_json("Invalid data")
    existing = _fb_get(f"data/{uid}/storeSettings")
    patch = {}
    for field, default in (("name","My Store"), ("tagline",""), ("logo","🛒"), ("logoImage",""), ("lang","AR"), ("currency","DZD")):
        if field in d:
            ok, value = _clean_store_setting(field, d[field], (existing or {}).get(field))
            if not ok:
                return err_json(f"قيمة غير صالحة للحقل: {field}")
            patch[field] = value
    if patch:
        if existing:
            _fb_patch(f"data/{uid}/storeSettings", patch)
        else:
            for field, default in (("name","My Store"), ("tagline",""), ("logo","🛒"), ("logoImage",""), ("lang","AR"), ("currency","DZD")):
                patch.setdefault(field, default)
            _fb_put(f"data/{uid}/storeSettings", patch)
    return ok_json(True)


@bp.route("/api/landing/questions", methods=["POST"])
@require_auth
@require_perm("landing")
def api_landing_questions():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    description = str(body.get("description") or "").strip()
    category = str(body.get("category") or "").strip()
    if not name:
        return err_json("اسم المنتج مطلوب")
    bot_settings = _fb_get(f"users/{request.auth_username}") or {}
    questions = _generate_landing_questions(bot_settings, name, description, category)
    return ok_json({"questions": questions})


@bp.route("/api/landing/generate", methods=["POST"])
@require_auth
@require_perm("landing")
def api_landing_generate():
    body      = request.get_json(silent=True) or {}
    uid       = request.auth_uid
    name      = str(body.get("name") or "").strip()
    desc      = str(body.get("description") or "").strip()
    raw_images = body.get("images") or []
    # فقط روابط https/http سليمة — يمنع حقن HTML/سكربت عبر حقل "صورة" بصفحة الهبوط العامة.
    images    = [x for x in raw_images if _sanitize_image_url(x)] if isinstance(raw_images, list) else []
    cta_type  = str(body.get("ctaType") or "store").strip()
    wa_number = re.sub(r"\D", "", str(body.get("whatsappNumber") or ""))
    answers   = body.get("answers") or {}

    if not name or not desc:
        return err_json("اسم المنتج والوصف مطلوبين")
    if not images:
        return err_json("أضف صورة واحدة على الأقل (رابط https صالح)")
    if cta_type not in ("store", "whatsapp"):
        cta_type = "store"
    if cta_type == "whatsapp" and not wa_number:
        return err_json("رقم واتساب مطلوب")
    if not planHas_server(uid, "landing"):
        return err_json("صفحات الهبوط غير متاحة لخطتك الحالية", 403)

    bot_settings = _fb_get(f"users/{request.auth_username}") or {}
    api_key = str(bot_settings.get("Gemini_api_key") or "").strip()
    copy = _generate_landing_copy(api_key, name, desc, answers)

    page_id = _new_landing_id(uid)
    record = {
        "id": page_id, "name": name,
        "description":   copy.get("description") or desc,
        "headline":       copy.get("headline") or name,
        "subheadline":    copy.get("subheadline", ""),
        "benefits":       copy.get("benefits", []),
        "urgencyText":    copy.get("urgencyText", ""),
        "guaranteeText":  copy.get("guaranteeText", ""),
        "faq":            copy.get("faq", []),
        "images": images[:4], "ctaType": cta_type, "whatsappNumber": wa_number,
        "published": True, "views": 0, "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "instagramPostId": "",
    }
    _fb_put(f"data/{uid}/landingPages/{page_id}", record)
    public_url = f"{request.url_root.rstrip('/')}/lp/{page_id}"
    return ok_json({"pageId": page_id, "publicUrl": public_url})


@bp.route("/api/landing/list", methods=["GET"])
@require_auth
@require_perm("landing")
def api_landing_list():
    uid = request.auth_uid
    raw = _fb_get(f"data/{uid}/landingPages") or {}
    items = []
    if isinstance(raw, dict):
        for pid, p in raw.items():
            if not isinstance(p, dict): continue
            items.append({**p, "id": pid, "publicUrl": f"{request.url_root.rstrip('/')}/lp/{pid}"})
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return ok_json(items)


@bp.route("/api/landing/togglePublish", methods=["POST"])
@require_auth
@require_perm("landing")
def api_landing_toggle_publish():
    body    = request.get_json(silent=True) or {}
    uid     = request.auth_uid
    page_id = str(body.get("pageId") or "").strip()
    if not page_id: return err_json("Missing pageId")
    page = _fb_get(f"data/{uid}/landingPages/{page_id}")
    if not page: return err_json("الصفحة غير موجودة", 404)
    _fb_patch(f"data/{uid}/landingPages/{page_id}", {"published": not page.get("published", True)})
    return ok_json(True)


@bp.route("/api/landing/delete", methods=["POST"])
@require_auth
@require_perm("landing")
def api_landing_delete():
    body    = request.get_json(silent=True) or {}
    uid     = request.auth_uid
    page_id = str(body.get("pageId") or "").strip()
    if not page_id: return err_json("Missing pageId")
    _fb_delete(f"data/{uid}/landingPages/{page_id}")
    return ok_json(True)


@bp.route("/api/landing/postToInstagram", methods=["POST"])
@require_auth
@require_perm("landing")
def api_landing_post_instagram():
    body    = request.get_json(silent=True) or {}
    uid     = request.auth_uid
    page_id = str(body.get("pageId") or "").strip()
    if not page_id: return err_json("Missing pageId")
    page = _fb_get(f"data/{uid}/landingPages/{page_id}")
    if not page: return err_json("الصفحة غير موجودة", 404)
    images = page.get("images") or []
    if not images: return err_json("لا توجد صورة لنشرها")

    fb_tokens  = _fb_get(f"data/{uid}/fbTokens") or {}
    ig_token   = str(fb_tokens.get("instgram_access_token") or "").strip()
    ig_page_id = str(fb_tokens.get("Page_ID_instgram") or "").strip()
    if not ig_token or not ig_page_id:
        return err_json("حساب إنستغرام غير مربوط — اربطه أولاً من الإعدادات", 400)

    caption = f"{page.get('name','')}\n\n{page.get('description','')}\n\n🔗 {request.url_root.rstrip('/')}/lp/{page_id}"
    try:
        r1 = requests.post(f"https://graph.facebook.com/v21.0/{ig_page_id}/media",
                            data={"image_url": images[0], "caption": caption[:2200], "access_token": ig_token},
                            timeout=20)
        r1_data = r1.json()
        if not r1.ok or "id" not in r1_data:
            logging.error(f"IG media create failed: {r1_data}")
            return err_json("فشل تجهيز المنشور: " + str((r1_data.get("error") or {}).get("message", "خطأ غير معروف")))
        creation_id = r1_data["id"]
        r2 = requests.post(f"https://graph.facebook.com/v21.0/{ig_page_id}/media_publish",
                            data={"creation_id": creation_id, "access_token": ig_token},
                            timeout=20)
        r2_data = r2.json()
        if not r2.ok or "id" not in r2_data:
            logging.error(f"IG publish failed: {r2_data}")
            return err_json("فشل نشر المنشور: " + str((r2_data.get("error") or {}).get("message", "خطأ غير معروف")))
        _fb_patch(f"data/{uid}/landingPages/{page_id}", {"instagramPostId": r2_data["id"]})
        return ok_json({"instagramPostId": r2_data["id"]})
    except Exception as e:
        logging.error(f"landing/postToInstagram: {e}")
        return err_json("خطأ فالاتصال بإنستغرام")


def _detect_image_kind(head):
    """يتعرّف على نوع الصورة من أول بايتات الملف (magic bytes) — بديل imghdr
    اللي انحذف من Python 3.13."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


@bp.route("/api/uploadImage", methods=["POST"])
@require_auth
def api_upload_image():
    """رفع آمن عبر السيرفر. قبل التعديل كان التحقق يعتمد فقط على امتداد اسم الملف
    و content_type القادم من المتصفح (كلاهما قابل للتزوير الكامل من العميل)، ما يسمح
    برفع HTML/SVG يحوي جافاسكريبت باسم ملف يبدو كصورة. الآن نفحص أول بايتات الملف
    فعلياً (magic bytes عبر _detect_image_kind) ونفرض content-type ثابت مطابق للمحتوى الحقيقي،
    ونولّد اسم الملف بالكامل بدل الوثوق باسم العميل."""
    if "file" not in request.files:
        return err_json("No file provided")
    file = request.files["file"]
    if not file or not file.filename:
        return err_json("Empty file")

    head = file.stream.read(512)
    file.stream.seek(0)
    kind = _detect_image_kind(head)
    allowed_mime = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
    if kind not in allowed_mime:
        return err_json("نوع الملف غير مدعوم — يجب أن يكون صورة حقيقية (jpg/png/gif/webp)")

    try:
        bucket    = fb_storage.bucket(FB_STORAGE_BUCKET)
        safe_ext  = {"jpeg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}[kind]
        blob_path = f"{request.auth_uid}/{int(time.time()*1000)}_{secrets.token_hex(6)}.{safe_ext}"
        blob      = bucket.blob(blob_path)
        blob.upload_from_file(file.stream, content_type=allowed_mime[kind])
        blob.make_public()
        return ok_json({"url": blob.public_url})
    except Exception as e:
        logging.error(f"uploadImage error: {e}")
        return err_json("فشل رفع الصورة", 500)
