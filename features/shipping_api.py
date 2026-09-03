# -*- coding: utf-8 -*-
"""
موديول الربط مع شركات الشحن الجزائرية (Yalidine كمثال أول، بنية قابلة للتوسيع).
قاعدة البيانات: data/{uid}/integrations/shipping/{provider}

⚠️ تنويه مهم: تفاصيل الـ base URL وطريقة الاعتماد (auth) تبع Yalidine موثّقة هون
حسب أحدث توثيق عام متوفر وقت كتابة هالكود (api.yalidine.app/v1 + API-ID/API-TOKEN
بالهيدرز). قبل ما تفعّليها بالإنتاج، تأكدي من أسماء الهيدرز بالظبط من لوحة تحكم
Yalidine (تبويب Développement → Tableau de bord) لأنها ممكن تتغير مع الوقت.
"""
import time
import logging
import requests
from flask import Blueprint, request
from app import (
    require_auth, require_perm, _fb_get, _fb_put, _fb_patch,
    _encrypt_secret, _decrypt_secret, ok_json, err_json,
    _validate_and_pin_store_url, _request_with_pinned_dns,
)

shipping_bp = Blueprint("shipping", __name__)

YALIDINE_BASE_URL = "https://api.yalidine.app/v1"


def _yalidine_headers(api_id, api_token):
    return {"X-API-ID": api_id, "X-API-TOKEN": api_token, "Content-Type": "application/json"}


@shipping_bp.route("/api/shipping/connect", methods=["POST"])
@require_auth
@require_perm("integrations")
def connect_shipping_provider():
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    provider = str(body.get("provider") or "").strip().lower()
    if provider != "yalidine":
        return err_json("مزوّد الشحن غير مدعوم حالياً — Yalidine فقط بهذا الإصدار")

    api_id = str(body.get("apiId") or "").strip()
    api_token = str(body.get("apiToken") or "").strip()
    if not api_id or not api_token:
        return err_json("API ID و API Token مطلوبين")

    # اختبار الاتصال — نفس مبدأ SSRF-safety المستعمل مع WooCommerce بالكود الأصلي
    hostname, safe_ip = _validate_and_pin_store_url(YALIDINE_BASE_URL)
    if not safe_ip:
        return err_json("تعذّر التحقق من عنوان Yalidine — حاول لاحقاً")
    try:
        test = _request_with_pinned_dns(
            "GET", f"{YALIDINE_BASE_URL}/wilayas", safe_ip,
            headers=_yalidine_headers(api_id, api_token), timeout=15,
        )
    except Exception as e:
        logging.error(f"shipping/connect test failed: {e}")
        return err_json("تعذر الاتصال بـ Yalidine")
    if test.status_code == 401:
        return err_json("API ID أو API Token غير صحيحين")
    if not test.ok:
        return err_json(f"خطأ من Yalidine (HTTP {test.status_code})")

    _fb_put(f"data/{uid}/integrations/shipping/yalidine", {
        "apiIdEnc": _encrypt_secret(api_id),
        "apiTokenEnc": _encrypt_secret(api_token),
        "connected": True,
        "connectedAt": time.strftime("%Y-%m-%d %H:%M"),
    })
    return ok_json(True)


@shipping_bp.route("/api/shipping/status", methods=["GET"])
@require_auth
@require_perm("integrations")
def shipping_status():
    uid = request.auth_uid
    data = _fb_get(f"data/{uid}/integrations/shipping/yalidine") or {}
    return ok_json({"connected": bool(data.get("connected")), "connectedAt": data.get("connectedAt", "")})


@shipping_bp.route("/api/shipping/disconnect", methods=["POST"])
@require_auth
@require_perm("integrations")
def shipping_disconnect():
    uid = request.auth_uid
    from app import _fb_delete
    _fb_delete(f"data/{uid}/integrations/shipping/yalidine")
    return ok_json(True)


@shipping_bp.route("/api/shipping/createShipment", methods=["POST"])
@require_auth
@require_perm("orders")
def create_shipment():
    """يُستدعى بزر 'أرسل للشحن' جنب كل طلب مؤكد بجدول الطلبات."""
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    order_id = str(body.get("orderId") or "").strip()
    if not order_id:
        return err_json("Missing orderId")

    order = _fb_get(f"data/{uid}/orders/{order_id}")
    if not order:
        return err_json("الطلب غير موجود", 404)

    integ = _fb_get(f"data/{uid}/integrations/shipping/yalidine")
    if not integ or not integ.get("connected"):
        return err_json("لم يتم ربط أي شركة شحن بعد")

    api_id = _decrypt_secret(integ.get("apiIdEnc", ""))
    api_token = _decrypt_secret(integ.get("apiTokenEnc", ""))
    if not api_id or not api_token:
        return err_json("فشل قراءة بيانات الربط — أعد ربط الشحن من جديد")

    hostname, safe_ip = _validate_and_pin_store_url(YALIDINE_BASE_URL)
    if not safe_ip:
        return err_json("تعذّر التحقق من عنوان Yalidine")

    # ⚠️ حقول parcel بالضبط (from_wilaya_id, to_commune_name, ...) لازم تتأكدي منها
    # بتوثيق Yalidine الرسمي — هاي بنية مبدئية شائعة الاستعمال.
    payload = [{
        "order_id": order_id,
        "firstname": order.get("name", "").split(" ")[0] or "—",
        "familyname": " ".join(order.get("name", "").split(" ")[1:]) or "—",
        "contact_phone": order.get("phone", ""),
        "address": order.get("address", ""),
        "to_commune_name": order.get("city", ""),
        "product_list": order.get("product", ""),
        "price": order.get("total", 0),
        "is_stopdesk": order.get("deliveryType") == "desk",
    }]

    try:
        r = _request_with_pinned_dns(
            "POST", f"{YALIDINE_BASE_URL}/parcels", safe_ip,
            headers=_yalidine_headers(api_id, api_token), json=payload, timeout=20,
        )
    except Exception as e:
        logging.error(f"createShipment failed: {e}")
        return err_json("تعذر الاتصال بـ Yalidine")

    if not r.ok:
        return err_json(f"فشل إنشاء الشحنة (HTTP {r.status_code})")

    resp_data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    tracking_id = ""
    try:
        first_key = list(resp_data.keys())[0]
        tracking_id = resp_data[first_key].get("tracking", "")
    except Exception:
        pass

    _fb_patch(f"data/{uid}/orders/{order_id}", {
        "shippingProvider": "yalidine",
        "shippingTracking": tracking_id,
        "shippingCreatedAt": time.strftime("%Y-%m-%d %H:%M"),
    })
    return ok_json({"trackingId": tracking_id})