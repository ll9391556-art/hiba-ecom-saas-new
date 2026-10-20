# -*- coding: utf-8 -*-
"""ربط WooCommerce (مع حماية SSRF وتثبيت DNS). منقول من app.py بلا تغيير (Phase 4 / A7)."""
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
    _fb_delete,
    _fb_get,
    _fb_keys,
    _fb_patch,
    _fb_put,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _decrypt_secret,
    _encrypt_secret,
    _request_with_pinned_dns,
    _validate_and_pin_store_url,
    require_auth,
    require_perm,
)
from services.orders import (
    _save_order,
)
from services.users import (
    _increment_usage,
    _under_cap,
)

bp = Blueprint("integrations", __name__)




# ── WooCommerce Integration ───────────────────────────────
@bp.route("/api/woo/connect", methods=["POST"])
@require_auth
@require_perm("integrations")
def api_woo_connect():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    store_url = str(body.get("storeUrl") or "").strip().rstrip("/")
    consumer_key    = str(body.get("consumerKey") or "").strip()
    consumer_secret = str(body.get("consumerSecret") or "").strip()
    if not store_url or not consumer_key or not consumer_secret:
        return err_json("جميع الحقول مطلوبة")
    if not store_url.startswith("https://"):
        return err_json("رابط المتجر يجب أن يبدأ بـ https:// لحماية بيانات متجرك")
    # حماية من SSRF (بما فيها DNS rebinding): نحلّ الدومين مرة واحدة، نتحقق أنه عام
    # وآمن، ثم نُثبّت نفس الـ IP وقت الاتصال الفعلي عبر _request_with_pinned_dns —
    # بواسطة session/adapter معزولين محلياً (بدون أي حالة عالمية) لتجنب أي تداخل بين
    # threads متزامنة أخرى فالسيرفر (انظر تعليق _PinnedHTTPSConnection فوق).
    hostname, safe_ip = _validate_and_pin_store_url(store_url)
    if not safe_ip:
        return err_json("رابط المتجر غير صالح أو يشير لعنوان غير مسموح به")
    try:
        test = _request_with_pinned_dns("GET", f"{store_url}/wp-json/wc/v3/orders", safe_ip,
                                         params={"per_page": 1},
                                         auth=(consumer_key, consumer_secret),
                                         timeout=15, allow_redirects=False)
    except Exception as e:
        logging.error(f"woo/connect test request failed: {e}")
        return err_json("تعذر الوصول للمتجر — تأكد من صحة الرابط")
    if test.status_code == 401:
        return err_json("مفاتيح API غير صحيحة (Consumer Key/Secret)")
    if not test.ok:
        return err_json(f"خطأ من المتجر (HTTP {test.status_code}) — تأكد أن WooCommerce REST API مفعّل")
    _fb_put(f"data/{uid}/integrations/woocommerce", {
        "storeUrl": store_url,
        "consumerKeyEnc":    _encrypt_secret(consumer_key),
        "consumerSecretEnc": _encrypt_secret(consumer_secret),
        "connected": True,
        "connectedAt": time.strftime("%Y-%m-%d %H:%M"),
        "lastSync": "",
    })
    return ok_json(True)


@bp.route("/api/woo/status", methods=["GET"])
@require_auth
@require_perm("integrations")
def api_woo_status():
    uid  = request.auth_uid
    data = _fb_get(f"data/{uid}/integrations/woocommerce") or {}
    return ok_json({
        "connected": bool(data.get("connected")),
        "storeUrl":  data.get("storeUrl", ""),
        "lastSync":  data.get("lastSync", ""),
    })


@bp.route("/api/woo/disconnect", methods=["POST"])
@require_auth
@require_perm("integrations")
def api_woo_disconnect():
    uid = request.auth_uid
    _fb_delete(f"data/{uid}/integrations/woocommerce")
    return ok_json(True)


@bp.route("/api/woo/sync", methods=["POST"])
@require_auth
@require_perm("integrations")
def api_woo_sync():
    uid   = request.auth_uid
    integ = _fb_get(f"data/{uid}/integrations/woocommerce")
    if not integ or not integ.get("connected"):
        return err_json("المتجر غير مربوط — اربطه أولاً")
    store_url = integ.get("storeUrl", "")
    # نفس فحص SSRF + تثبيت DNS عند كل مزامنة — الرابط المخزّن سابقاً قد يكون DNS تغيّر
    # لاحقاً (DNS rebinding) لذلك نعيد الحل والتثبيت فكل استعمال فعلي وليس فقط عند الربط.
    hostname, safe_ip = _validate_and_pin_store_url(store_url)
    if not safe_ip:
        return err_json("رابط المتجر المحفوظ غير صالح — أعد ربط المتجر من جديد")
    ck = _decrypt_secret(integ.get("consumerKeyEnc", ""))
    cs = _decrypt_secret(integ.get("consumerSecretEnc", ""))
    if not ck or not cs:
        return err_json("فشل قراءة بيانات الربط — أعد ربط المتجر من جديد")
    try:
        r = _request_with_pinned_dns("GET", f"{store_url}/wp-json/wc/v3/orders", safe_ip,
                          params={"per_page": 50, "orderby": "date", "order": "desc"},
                          auth=(ck, cs), timeout=20, allow_redirects=False)
    except Exception as e:
        logging.error(f"woo/sync request failed: {e}")
        return err_json("تعذر الاتصال بالمتجر")
    if not r.ok:
        return err_json(f"خطأ من المتجر (HTTP {r.status_code})")
    try:
        woo_orders = r.json()
        if not isinstance(woo_orders, list): woo_orders = []
    except Exception:
        woo_orders = []

    # مفاتيح الطلبات فقط (shallow) — طلبات Woo مفتاحها دائماً ORD-WOO-<id>
    existing_keys = _fb_keys(f"data/{uid}/orders")
    if existing_keys is None:
        return err_json("تعذّر قراءة الطلبات الحالية — حاول بعد قليل", 503)
    existing_keys = set(existing_keys)
    imported = 0
    for wo in woo_orders:
        if not _under_cap(uid, "orderCount", "orderCap"):
            logging.warning(f"⏭️ توقفت مزامنة WooCommerce — تجاوز سقف الطلبات الشهري | uid={uid}")
            break
        woo_id = str(wo.get("id", ""))
        if not woo_id or f"ORD-WOO-{woo_id}" in existing_keys: continue
        billing     = wo.get("billing", {}) or {}
        line_items  = wo.get("line_items", []) or []
        product     = line_items[0].get("name", "") if line_items else ""
        qty         = line_items[0].get("quantity", 1) if line_items else 1
        order_id    = f"ORD-WOO-{woo_id}"
        full_name   = f"{billing.get('first_name','')} {billing.get('last_name','')}".strip()
        new_order = {
            "id": order_id, "wooOrderId": woo_id,
            "date": (wo.get("date_created") or "").replace("T", " ")[:16] or time.strftime("%Y-%m-%d %H:%M"),
            "status": "Pending", "profit": 0, "source": "woocommerce", "deliveryType": "home",
            "date_sent": "", "date_delivered": "",
            "name": full_name or "—", "phone": billing.get("phone", ""),
            "product": product, "qty": int(qty) if str(qty).isdigit() else 1,
            "city": billing.get("city", ""), "address": billing.get("address_1", ""),
            "unitPrice": 0, "shipping": 0, "total": float(wo.get("total", 0) or 0),
        }
        _save_order(uid, order_id, new_order)
        _increment_usage(uid, "orderCount")
        imported += 1
    _fb_patch(f"data/{uid}/integrations/woocommerce", {"lastSync": time.strftime("%Y-%m-%d %H:%M")})
    return ok_json({"imported": imported, "checked": len(woo_orders)})
