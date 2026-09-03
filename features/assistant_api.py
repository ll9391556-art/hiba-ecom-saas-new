# -*- coding: utf-8 -*-
"""
موديول البوت الإداري — يتكلم مع التاجر نفسه (مختلف عن بوت خدمة الزبائن الموجود).
قاعدة البيانات: admin_chats/{uid}/{messageId} + data/{uid}/auditLog/{entryId}

يعيد استخدام _gemini_generate_with_fallback الجاهزة من app.py — بلا إعادة تطبيق
منطق fallback بين نماذج Gemini من الصفر.
"""
import time
import logging
import requests as _requests
from flask import Blueprint, request
from google.genai import types
from app import (
    require_auth, require_owner, require_perm, _fb_get, _fb_push, _fb_list, _fb_put, _fb_patch,
    _gemini_generate_with_fallback, _usage_month_key, ok_json, err_json,
    _encrypt_secret, _decrypt_secret, _validate_and_pin_store_url, _request_with_pinned_dns,
)

assistant_bp = Blueprint("assistant", __name__)


# ── تسجيل تدقيق (Audit Log) — دالة تُستدعى من نقاط حساسة بالكود الأصلي ──
def log_audit_entry(uid, actor, action, details=""):
    try:
        _fb_push(f"data/{uid}/auditLog", {
            "actor": actor, "action": action, "details": details,
            "timestamp": time.time(), "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        logging.error(f"log_audit_entry: {e}")


def _build_business_summary(orders, products, team, usage, audit_log):
    orders = orders if isinstance(orders, dict) else {}
    products = products if isinstance(products, dict) else {}
    total = len(orders)
    confirmed = sum(1 for o in orders.values() if isinstance(o, dict) and o.get("status") in ("Confirmed", "Delivered"))
    refused = sum(1 for o in orders.values() if isinstance(o, dict) and o.get("status") == "Refused")
    profit = sum(float(o.get("profit", 0) or 0) for o in orders.values() if isinstance(o, dict))
    low_stock = [p.get("name") for p in products.values() if isinstance(p, dict) and int(p.get("available", 0) or 0) <= 5]
    team_count = len([1 for v in (team or {}).values() if isinstance(v, dict)])

    recent_errors = []
    if isinstance(audit_log, dict):
        entries = sorted(audit_log.values(), key=lambda x: x.get("timestamp", 0), reverse=True)[:15]
        recent_errors = [f"{e.get('actor','?')}: {e.get('action','')} — {e.get('details','')}" for e in entries]

    return f"""
- إجمالي الطلبات: {total}
- الطلبات المؤكدة/المسلَّمة: {confirmed}
- الطلبات المرفوضة: {refused}
- معدل التأكيد: {round(confirmed/total*100) if total else 0}%
- إجمالي الأرباح المسجّلة: {round(profit,2)}
- عدد المنتجات بمخزون منخفض (≤5): {len(low_stock)} — {', '.join(low_stock[:10]) or 'لا يوجد'}
- عدد أعضاء الفريق: {team_count}
- استهلاك رسائل البوت هالشهر: {usage.get('botMsgCount', 0)}
- استهلاك الطلبات هالشهر: {usage.get('orderCount', 0)}
- آخر عمليات الفريق المسجّلة: {'; '.join(recent_errors) if recent_errors else 'لا يوجد سجل بعد'}
""".strip()


@assistant_bp.route("/api/assistant/ask", methods=["POST"])
@require_auth
@require_owner
def ask_admin_assistant():
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    question = str(body.get("message") or "").strip()[:1000]
    if not question:
        return err_json("اكتب سؤالك أولاً")

    bot_settings = _fb_get(f"users/{request.auth_username}") or {}
    api_key = str(bot_settings.get("Gemini_api_key") or "").strip()
    if not api_key:
        return err_json("لازم تضبطي مفتاح Gemini API من إعدادات البوت أولاً")

    orders = _fb_get(f"data/{uid}/orders") or {}
    products = _fb_get(f"data/{uid}/products") or {}
    team = _fb_get(f"data/{uid}/teamMembers") or {}
    usage = _fb_get(f"data/{uid}/usage/{_usage_month_key()}") or {}
    audit_log = _fb_get(f"data/{uid}/auditLog") or {}

    summary = _build_business_summary(orders, products, team, usage, audit_log)
    history_raw = _fb_list(f"admin_chats/{uid}")[:6]
    history_text = "\n".join(
        f"{'التاجر' if h.get('role')=='user' else 'المساعد'}: {h.get('content','')}"
        for h in reversed(history_raw)
    )

    prompt = f"""أنت مستشار أعمال ذكي لصاحب متجر إلكتروني بالجزائر. بيانات متجره الحالية:
{summary}

سجل المحادثة السابق (إن وجد):
{history_text}

سؤال التاجر الحالي: {question}

جاوب بالعربية أو الدارجة (بنفس لغة السؤال)، بشكل عملي ومباشر، اقترح خطوات محددة قابلة للتنفيذ.
إذا لاحظت مؤشر سلبي بالبيانات (معدل رفض مرتفع، مخزون منخفض، نشاط غير معتاد من عضو فريق)، نبّه عليه حتى لو ما سُئلت عنه مباشرة."""

    try:
        contents = [types.Part.from_text(text=prompt)]
        cfg = types.GenerateContentConfig(temperature=0.4, max_output_tokens=700)
        answer, _ = _gemini_generate_with_fallback(api_key, contents, cfg, "admin_assistant")
    except Exception as e:
        logging.error(f"admin assistant error: {e}")
        return err_json("تعذّر الحصول على رد الآن، حاول بعد قليل")

    now = time.time()
    _fb_push(f"admin_chats/{uid}", {"role": "user", "content": question, "timestamp": now})
    _fb_push(f"admin_chats/{uid}", {"role": "assistant", "content": answer, "timestamp": now + 0.001})

    return ok_json({"reply": answer})


@assistant_bp.route("/api/assistant/history", methods=["GET"])
@require_auth
@require_owner
def assistant_history():
    uid = request.auth_uid
    items = _fb_list(f"admin_chats/{uid}")[:40]
    return ok_json(list(reversed(items)))


@assistant_bp.route("/api/assistant/weeklyReport", methods=["GET"])
@require_auth
@require_owner
def weekly_report():
    """تقرير جاهز بدون سؤال — يُستدعى مرة وحدة وقت فتح صفحة المساعد."""
    uid = request.auth_uid
    orders = _fb_get(f"data/{uid}/orders") or {}
    products = _fb_get(f"data/{uid}/products") or {}
    team = _fb_get(f"data/{uid}/teamMembers") or {}
    usage = _fb_get(f"data/{uid}/usage/{_usage_month_key()}") or {}
    audit_log = _fb_get(f"data/{uid}/auditLog") or {}
    summary = _build_business_summary(orders, products, team, usage, audit_log)
    return ok_json({"summary": summary})


@assistant_bp.route("/api/assistant/auditLog", methods=["GET"])
@require_auth
@require_owner
def get_audit_log():
    uid = request.auth_uid
    limit = min(int(request.args.get("limit", 100) or 100), 300)
    items = _fb_list(f"data/{uid}/auditLog")[:limit]
    return ok_json(items)


# ── تكلفة إعلانات ميتا الممولة ──────────────────────────────────────
@assistant_bp.route("/api/assistant/adInsights", methods=["GET"])
@require_auth
@require_owner
def ad_insights():
    uid = request.auth_uid
    fb_tokens = _fb_get(f"data/{uid}/fbTokens") or {}
    ad_account_id = str(fb_tokens.get("adAccountId") or "").strip()
    access_token = str(fb_tokens.get("fb_access_token") or "").strip()
    if not ad_account_id or not access_token:
        return err_json("لازم تربطي حساب فيسبوك الإعلاني أولاً (act_XXXXXXXXXX) من إعدادات المساعد")
    try:
        r = _requests.get(
            f"https://graph.facebook.com/v21.0/{ad_account_id}/insights",
            params={
                "access_token": access_token,
                "fields": "spend,impressions,clicks,cpc,cpm,actions",
                "date_preset": request.args.get("period", "last_7d"),
            },
            timeout=15,
        )
        data = r.json()
        if not r.ok:
            return err_json("فشل جلب بيانات الإعلانات من ميتا — تأكدي من صلاحية الحساب")
        return ok_json(data.get("data", []))
    except Exception as e:
        logging.error(f"ad_insights: {e}")
        return err_json("تعذر الاتصال بميتا")


# ── موديول الربط مع شركات الشحن (Yalidine كمثال أول) ──────────────────
YALIDINE_BASE_URL = "https://api.yalidine.app/v1"


def _yalidine_headers(api_id, api_token):
    return {"X-API-ID": api_id, "X-API-TOKEN": api_token, "Content-Type": "application/json"}


@assistant_bp.route("/api/shipping/connect", methods=["POST"])
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


@assistant_bp.route("/api/shipping/status", methods=["GET"])
@require_auth
@require_perm("integrations")
def shipping_status():
    uid = request.auth_uid
    data = _fb_get(f"data/{uid}/integrations/shipping/yalidine") or {}
    return ok_json({"connected": bool(data.get("connected")), "connectedAt": data.get("connectedAt", "")})


@assistant_bp.route("/api/shipping/disconnect", methods=["POST"])
@require_auth
@require_perm("integrations")
def shipping_disconnect():
    uid = request.auth_uid
    from app import _fb_delete
    _fb_delete(f"data/{uid}/integrations/shipping/yalidine")
    return ok_json(True)


@assistant_bp.route("/api/shipping/createShipment", methods=["POST"])
@require_auth
@require_perm("orders")
def create_shipment():
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