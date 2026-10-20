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
    require_auth, require_owner, _fb_get, _fb_push,
    _gemini_generate_with_fallback, _usage_month_key, ok_json, err_json,
    _fb_query, _get_stats, _sold_by_name, _stock_fields, _safe_int,
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


def _latest(path, n):
    """آخر n عناصر (مفاتيح push مرتّبة زمنياً) — الأحدث أولاً. بدل تنزيل العقدة كاملة."""
    found = _fb_query(path, "$key", limit_last=n) or {}
    return [v for v in reversed(list(found.values())) if isinstance(v, dict)]


def _build_business_summary(stats, products, team, usage, audit_entries):
    """من data/{uid}/stats (المجاميع الجارية) بدل كل الطلبات، والمخزون محسوب من stats.sales."""
    stats = stats if isinstance(stats, dict) else {}
    products = products if isinstance(products, dict) else {}
    total = _safe_int(stats.get("total"))
    confirmed = _safe_int(stats.get("confirmed"))
    refused = _safe_int(stats.get("refused"))
    profit = _safe_int(stats.get("profitCents")) / 100
    sold = _sold_by_name(stats)
    low_stock = [p.get("name") for p in products.values()
                 if isinstance(p, dict) and _stock_fields(p, sold.get(p.get("name", ""), 0))["available"] <= 5]
    team_count = len([1 for v in (team or {}).values() if isinstance(v, dict)])

    recent_errors = [f"{e.get('actor','?')}: {e.get('action','')} — {e.get('details','')}"
                     for e in (audit_entries or [])[:15]]

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

    summary = _summary_for(uid)
    history_raw = _latest(f"admin_chats/{uid}", 6)
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
    items = _latest(f"admin_chats/{uid}", 40)
    return ok_json(list(reversed(items)))


@assistant_bp.route("/api/assistant/weeklyReport", methods=["GET"])
@require_auth
@require_owner
def weekly_report():
    """تقرير جاهز بدون سؤال — يُستدعى مرة وحدة وقت فتح صفحة المساعد."""
    uid = request.auth_uid
    return ok_json({"summary": _summary_for(uid)})


def _summary_for(uid):
    return _build_business_summary(
        _get_stats(uid), _fb_get(f"data/{uid}/products") or {},
        _fb_get(f"data/{uid}/teamMembers") or {},
        _fb_get(f"data/{uid}/usage/{_usage_month_key()}") or {},
        _latest(f"data/{uid}/auditLog", 15))


@assistant_bp.route("/api/assistant/auditLog", methods=["GET"])
@require_auth
@require_owner
def get_audit_log():
    uid = request.auth_uid
    limit = min(int(request.args.get("limit", 100) or 100), 300)
    return ok_json(_latest(f"data/{uid}/auditLog", limit))


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


# /api/shipping/* كانت معرّفة هنا مرة ثانية (نسخة ميتة: shipping_bp يتسجّل قبل assistant_bp
# فيلقط المسارات أولاً). المسارات الحقيقية فـ features/shipping_api.py.
