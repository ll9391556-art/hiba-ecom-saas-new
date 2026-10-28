# -*- coding: utf-8 -*-
"""إعدادات المتجر، تسيير صفحات الهبوط، ورفع الصور. منقول من app.py بلا تغيير (Phase 4 / A7)."""
import hashlib
import hmac
import io
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
    DEFAULT_STORE_COLOR,
    FB_STORAGE_BUCKET,
    STORE_COLORS,
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
_STORE_DEFAULTS    = (("name","My Store"), ("tagline",""), ("logo","🛒"), ("logoImage",""), ("lang","AR"),
                      ("currency","DZD"), ("color", DEFAULT_STORE_COLOR))


def _logo_blob_prefix(uid):
    return f"{uid}/logo_"


def _is_own_logo_url(url, uid):
    """الرابط هو بالضبط public_url تاع {uid}/logo_<ms>_<hex12>.png (بلا ../ ولا مسار آخر)."""
    prefix = fb_storage.bucket(FB_STORAGE_BUCKET).blob(_logo_blob_prefix(uid)).public_url
    return url.startswith(prefix) and re.fullmatch(r"[0-9]+_[0-9a-f]{12}\.png", url[len(prefix):]) is not None


def _clean_store_setting(field, value, current, uid=None):
    """تحقق خفيف لإعدادات المتجر: نوع + طول فقط، بلا فلترة حروف (عربي/فرنسي/إيموجي يمرّو كما هم —
    الحماية من XSS بالتهريب وقت العرض). قيمة مطابقة للمخزّنة حالياً تتقبل دائماً باش المتاجر
    القديمة تقدر تعاود تحفظ."""
    if current is not None and value == current:
        return True, value
    if field == "logoImage":
        # D4a: شعار جديد = غير اللي ترفع بـ /api/uploadStoreLogo فمجلد التاجر نفسو (ولا "" للحذف).
        # الروابط القديمة (برّانية) تبقى مقبولة كي ما تتبدّلش (الشرط فوق).
        if value == "":
            return True, ""
        return (isinstance(value, str) and _is_own_logo_url(value, uid), value)
    if field == "currency":
        return (value in _STORE_CURRENCIES, value)
    if field == "color":
        return (isinstance(value, str) and value in STORE_COLORS, value)
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
    for field, default in _STORE_DEFAULTS:
        if field in d:
            ok, value = _clean_store_setting(field, d[field], (existing or {}).get(field), uid)
            if not ok:
                return err_json(f"قيمة غير صالحة للحقل: {field}")
            patch[field] = value
    if patch:
        if existing:
            _fb_patch(f"data/{uid}/storeSettings", patch)
        else:
            for field, default in _STORE_DEFAULTS:
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


_IMAGE_MIME       = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
_IMAGE_EXT        = {"jpeg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}
_PIL_FORMAT       = {"jpeg": "JPEG", "png": "PNG", "gif": "GIF", "webp": "WEBP"}
UPLOAD_MAX_BYTES  = 5 * 1024 * 1024
PRODUCT_MAX_SIDE  = 1200          # D4a: صور المتجر بمقاس يناسب الهاتف
_MAX_IMAGE_PIXELS = 40_000_000    # ضد decompression bomb (صورة صغيرة فالحجم وضخمة بالبكسلات)


def _read_upload(max_bytes):
    """(bytes, None) ولا (None, رسالة خطأ). يقرا حتى max_bytes + 1 برك."""
    file = request.files.get("file")
    if not file or not file.filename:
        return None, "No file provided"
    data = file.stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        return None, f"الحجم الأقصى {max_bytes // (1024 * 1024)}MB"
    return data, None


def _open_image(data, kind):
    """يفك الصورة فعلاً بـ Pillow (magic bytes صحيحة وباقي الملف مزوّر → None).
    Pillow يتستورد هنا باش الـ workers ما يحمّلوهش حتى يتحتاج."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        if img.format != _PIL_FORMAT[kind]:
            return None
        if kind == "jpeg":
            img.draft("RGB", (PRODUCT_MAX_SIDE, PRODUCT_MAX_SIDE))  # فك JPEG مصغّر: ذاكرة أقل
        img.load()
        return ImageOps.exif_transpose(img)  # صور الهاتف: الاتجاه قبل ما يتنحّى EXIF
    except Exception:
        return None


def _encode_image(img, kind):
    """إعادة ترميز بنفس الصيغة وبلا metadata (EXIF، GPS...)."""
    out = io.BytesIO()
    if kind == "jpeg":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=85, optimize=True, progressive=True)
    elif kind == "webp":
        img.save(out, format="WEBP", quality=85)
    else:
        img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _store_upload(blob_path, data, mime):
    bucket = fb_storage.bucket(FB_STORAGE_BUCKET)
    blob   = bucket.blob(blob_path)
    blob.upload_from_file(io.BytesIO(data), content_type=mime)
    blob.make_public()
    return blob.public_url


@bp.route("/api/uploadImage", methods=["POST"])
@require_auth
def api_upload_image():
    """رفع آمن عبر السيرفر. قبل التعديل كان التحقق يعتمد فقط على امتداد اسم الملف
    و content_type القادم من المتصفح (كلاهما قابل للتزوير الكامل من العميل)، ما يسمح
    برفع HTML/SVG يحوي جافاسكريبت باسم ملف يبدو كصورة. الآن نفحص أول بايتات الملف
    فعلياً (magic bytes عبر _detect_image_kind) ونفرض content-type ثابت مطابق للمحتوى الحقيقي،
    ونولّد اسم الملف بالكامل بدل الوثوق باسم العميل.
    D4a: حتى 5MB، والصورة تتفك فعلاً (ملف مزوّر → 400) وتتصغّر لـ 1200px وتتعاود تترمّز بلا
    metadata. GIF يتخزّن كما هو (باش ما تضيعش الحركة) بعد ما يتأكد أنه يتفك."""
    data, error = _read_upload(UPLOAD_MAX_BYTES)
    if error:
        return err_json(error)
    kind = _detect_image_kind(data[:512])
    if kind not in _IMAGE_MIME:
        return err_json("نوع الملف غير مدعوم — يجب أن يكون صورة حقيقية (jpg/png/gif/webp)")
    img = _open_image(data, kind)
    if img is None:
        return err_json("الملف ماهوش صورة صالحة")
    if kind != "gif":
        img.thumbnail((PRODUCT_MAX_SIDE, PRODUCT_MAX_SIDE))
        data = _encode_image(img, kind)

    try:
        blob_path = f"{request.auth_uid}/{int(time.time()*1000)}_{secrets.token_hex(6)}.{_IMAGE_EXT[kind]}"
        return ok_json({"url": _store_upload(blob_path, data, _IMAGE_MIME[kind])})
    except Exception as e:
        logging.error(f"uploadImage error: {e}")
        return err_json("فشل رفع الصورة", 500)


LOGO_MAX_BYTES = 1 * 1024 * 1024
LOGO_SIZE      = 256
_LOGO_KINDS    = ("png", "jpeg", "webp")  # بلا SVG (سكريبت) وبلا GIF


@bp.route("/api/uploadStoreLogo", methods=["POST"])
@require_auth
@require_perm("store")
def api_upload_store_logo():
    """شعار المتجر (D4a): PNG/JPG/WEBP حتى 1MB، يتفك فعلاً، ويتخزّن PNG مربع 256×256
    (الشعار كامل داخل المربع والباقي شفاف) فـ {uid}/logo_... . ما يحفظش الإعدادات:
    الرابط يتبعث مع "حفظ" لـ updateStoreSettings اللي يقبل غير شعارات مجلد التاجر."""
    data, error = _read_upload(LOGO_MAX_BYTES)
    if error:
        return err_json(error)
    kind = _detect_image_kind(data[:512])
    if kind not in _LOGO_KINDS:
        return err_json("الشعار لازم يكون PNG ولا JPG ولا WEBP")
    img = _open_image(data, kind)
    if img is None:
        return err_json("الملف ماهوش صورة صالحة")

    from PIL import Image
    img = img.convert("RGBA")
    img.thumbnail((LOGO_SIZE, LOGO_SIZE))
    square = Image.new("RGBA", (LOGO_SIZE, LOGO_SIZE), (0, 0, 0, 0))
    square.paste(img, ((LOGO_SIZE - img.width) // 2, (LOGO_SIZE - img.height) // 2), img)

    try:
        blob_path = f"{_logo_blob_prefix(request.auth_uid)}{int(time.time()*1000)}_{secrets.token_hex(6)}.png"
        return ok_json({"url": _store_upload(blob_path, _encode_image(square, "png"), "image/png")})
    except Exception as e:
        logging.error(f"uploadStoreLogo error: {e}")
        return err_json("فشل رفع الشعار", 500)
