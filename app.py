import os
import json
import hmac
import hashlib
import logging
import requests
import time
import re
import secrets
import threading
import bcrypt
import jwt
import ipaddress
import socket
import urllib3
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.poolmanager import PoolManager
from cryptography.fernet import Fernet, InvalidToken
from functools import wraps
from urllib.parse import unquote, quote, urlparse
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, abort, jsonify, send_from_directory, make_response
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import firebase_admin
from firebase_admin import credentials, db, storage as fb_storage
from google import genai
from google.genai import types
from time import sleep
from markupsafe import escape as _esc

# Phase 4: الطبقات المشتركة فـ core/ — app.py يعاود يصدّر نفس الأسماء، باش features/*
# والاختبارات (`from app import ...`) يبقاو خدامين بلا تبديل.
from core.db import (_FB_TRANSIENT_ERRORS, _fb_is_transient, _fb_call, _fb_get, _fb_query, _fb_keys,
                     _fb_put, _fb_patch, _fb_delete, _fb_push, _fb_list, _firebase_ref)
from core.http import ok_json, err_json, _opt_int_arg, _opt_float_arg
from core.audit import log_audit_entry
# Phase 4 / A4: services/ — منطق الأعمال (الطلبات والمجاميع، الحسابات، الكوبونات)
import services.orders as _orders_svc  # _now_ms: الاختبارات تعدّلو فـ services.orders
from services.orders import (
    _store_products_cache,
    _store_products_cache_lock,
    _STORE_CACHE_TTL,
    _order_created_ms,
    _phone_digits,
    _with_index_fields,
    _save_order,
    _AGG_ORDER_FIELDS,
    _patch_order,
    _SOLD_STATUSES,
    _STAT_COUNTERS,
    _agg_key,
    _order_contrib,
    _stats_delta,
    _add_to_stats,
    _compute_stats,
    _customer_from_orders,
    _compute_customers,
    _refresh_customer,
    _invalidate_store_cache,
    _CUSTOMER_FIELDS,
    _apply_order_change,
    _add_rating_to_stats,
    _get_stats,
    _sold_by_name,
    _stock_fields,
    _recompute_aggregates,
    _ship_values,
    _calc_order_profit,
    _rebuild_order_fields,
)
from services.users import (
    _settings_cache,
    _settings_cache_lock,
    _CACHE_TTL,
    _NEG_CACHE_TTL,
    _count_team_members,
    _usage_month_key,
    _get_usage,
    _increment_usage,
    _plan_cap,
    _under_cap,
    _get_user_record,
    get_user_plan,
    _LIFETIME_PLANS,
    _uname_key,
    _username_taken,
    _count_lifetime_accounts,
    _LifetimeFull,
    _adjust_lifetime_counter,
    _PROTECTED_USER_FIELDS,
    _sanitize_bot_settings_patch,
    planHas_server,
    _CHANNEL_FIELDS,
    _channel_ids,
    _save_bot_settings,
    _rebuild_user_indexes,
)
from services.coupons import (
    _validate_and_apply_coupon,
    _increment_coupon_usage,
)
# Phase 4 / A5: البوت فـ services/bot.py (الاختبارات تعوّض _executor/get_user_settings/process_bg هناك)
from services.bot import (
    _executor,
    last_msg_time,
    _rate_limit_lock,
    _recent_bot_orders,
    _recent_bot_orders_lock,
    _DUPLICATE_ORDER_WINDOW,
    _is_duplicate_bot_order,
    _mark_bot_order,
    _cleanup_rate_limit,
    is_rate_limited,
    _migrate_bot_logs,
    get_user_settings,
    _bot_allowed_for,
    meta_post,
    send_facebook_message,
    send_whatsapp_message,
    get_media_url,
    download_media,
    _gemini_generate_with_fallback,
    get_history,
    save_history,
    history_to_text,
    log_ai_message,
    _log_conversation,
    get_products_text,
    extract_json,
    _find_field,
    _normalize_delivery_type,
    validate_order,
    save_order_from_bot,
    ask_gemini,
    process_bg,
    _webhook_object,
    verify_sig,
    _STICKERS,
    _sticker_i,
    _sticker_lk,
    sticker_reply,
    handle_webhook_payload,
    submit_webhook,
)
from services.landing import (
    LANDING_ID_PREFIX,
    _new_landing_id,
    _landing_uid_from_id,
    _sanitize_image_url,
    DEFAULT_LANDING_QUESTIONS,
    _generate_landing_questions,
    _generate_landing_copy,
    _build_landing_html,
)
from core.util import _safe_int, _cents, _mask_id
from core.security import (
    _encrypt_secret, _decrypt_secret, issue_token, decode_token, _extract_bearer,
    require_auth, require_perm, require_admin, require_owner,
    _is_bcrypt_hash, _hash_password, _verify_password,
    _login_attempts, _login_lock, _login_rate_limited, _cleanup_login_attempts,
    _RATE_LIMITS, _RL_SALT, _rl_hash, _shared_limited, _any_shared_limited, _cleanup_shared_limits,
    _clean_perms, _resolve_safe_public_ip, _validate_and_pin_store_url,
    _PinnedHTTPSConnection, _make_pinned_https_adapter, _request_with_pinned_dns,
)
from core.config import (
    _TRUSTED_PROXY_HOPS,
    _fernet,
    _ALLOWED_ORIGINS,
    MAX_PAYLOAD_SIZE,
    MAX_HISTORY_TURNS,
    LOW_STOCK_THRESHOLD,
    BAD_CUSTOMER_THRESHOLD,
    _JSON_START,
    _JSON_END,
    _GEMINI_MODELS,
    VERIFY_TOKEN,
    META_APP_SECRET,
    FB_DB_URL,
    FB_APP_ID,
    FB_APP_SECRET_OAUTH,
    REDIRECT_URI,
    FB_STORAGE_BUCKET,
    JWT_SECRET,
    JWT_ALGO,
    JWT_EXPIRY_HOURS_OWNER,
    JWT_EXPIRY_HOURS_MEMBER,
    ADMIN_API_KEY,
    ENCRYPTION_KEY,
    _IS_PRODUCTION,
    _boot_problems,
    _enc_env,
    PLANS,
    CURRENCY_SYMBOLS_PY,
    BOT_LAUNCHED,
    MAX_TEAM_MEMBERS,
    TEAM_PERM_KEYS,
    LIFETIME_MAX_SLOTS,
)

app = Flask(__name__, static_folder="static")

# ── ثقة بروكسي عكسي (X-Forwarded-For) ──────────────────────
# قبل: كل مسار كان يقرأ X-Forwarded-For يدوياً مباشرة من الهيدر القادم من العميل
# (request.headers.get("X-Forwarded-For", ...).split(",")[0]) بلا أي تحقق من عدد
# البروكسيات الفعلي بينه وبين الطلب. أي مهاجم يقدر يبعث قيمة X-Forwarded-For عشوائية
# مختلفة بكل طلب ليتحايل بالكامل على: rate limiting لتسجيل الدخول، rate limiting على
# ADMIN_API_KEY brute-force، وrate limiting على /api/addOrder. الآن: نستعمل ProxyFix
# لجعل Flask يثق فقط بأول قيمة قادمة من بروكسي واحد موثوق (منصة الاستضافة نفسها)
# ونعتمد على request.remote_addr المُصحَّح فكل مكان بدل الهيدر الخام.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_TRUSTED_PROXY_HOPS, x_proto=1, x_host=0, x_port=0, x_prefix=0)

# ── CORS ──────────────────────────────────────────────────
# قبل: origins="*" على كل المسارات (بما فيها /admin و/api/admin/*).
# الآن: مقيّد بقائمة من متغير بيئة ALLOWED_ORIGINS (مفصولة بفواصل)، بقيمة افتراضية
# تقتصر على دومين المنتج فقط بدل فتحه للعالم كله.
# /api/getOAuthState وحدو يقبل credentials: يحط كوكي nonce ديال ربط فيسبوك (SEC-004).
CORS(app, resources={r"/api/getOAuthState": {"origins": _ALLOWED_ORIGINS, "supports_credentials": True},
                     r"/*": {"origins": _ALLOWED_ORIGINS}}, supports_credentials=False)


threading.Thread(target=_cleanup_login_attempts, daemon=True).start()


# keepalive: انتقل لـ gunicorn.conf.py (when_ready) — ping وحيد من master gunicorn بدل
# خيط فكل worker، وبلا fallback لـ localhost:10000 (كان بالبورت الغلط).


threading.Thread(target=_cleanup_rate_limit, daemon=True).start()

# ── Firebase ──────────────────────────────────────────────
def _init_firebase():
    if not firebase_admin._apps:
        creds_str = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
        if not creds_str:
            logging.error("FIREBASE_CREDENTIALS missing")
            return
        try:
            cred = credentials.Certificate(json.loads(creds_str))
            firebase_admin.initialize_app(cred, {
                "databaseURL": FB_DB_URL + "/",
                "storageBucket": FB_STORAGE_BUCKET,
            })
            logging.info("✅ Firebase Connected")
        except Exception as e:
            logging.error(f"Firebase init error: {e}")

_init_firebase()


# ── Plans ─────────────────────────────────────────────────
# PLANS والثوابت فـ core/config.py


@app.route("/admin", methods=["GET"])
def admin_page():
    return """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>OrderFlow — إدارة عملاء Fiverr</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1b2e;color:#e8edf5;font-family:'Segoe UI',Arial,sans-serif;padding:24px;min-height:100vh}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:22px;margin-bottom:4px}
p.sub{color:#8899bb;font-size:13px;margin-bottom:20px}
.card{background:#111f35;border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:22px;margin-bottom:20px}
.card h2{font-size:15px;margin-bottom:14px;color:#60a5fa}
label{display:block;font-size:12px;color:#8899bb;margin-bottom:5px;margin-top:12px}
input,select{width:100%;background:#0f1c30;border:1px solid rgba(255,255,255,.08);color:#e8edf5;border-radius:8px;padding:9px 12px;font-size:13px}
button{background:#2563eb;color:#fff;border:none;border-radius:8px;padding:10px 18px;font-size:13px;font-weight:700;cursor:pointer;margin-top:16px}
button:hover{background:#1d4ed8}
button:disabled{opacity:.5;cursor:not-allowed}
.msg{margin-top:14px;padding:12px;border-radius:8px;font-size:12px;display:none}
.msg.ok{background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3);color:#10b981;display:block}
.msg.err{background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.3);color:#ef4444;display:block}
.result-box{background:#0a1628;border-radius:8px;padding:14px;margin-top:10px;font-size:12px;line-height:1.8}
.result-box code{color:#60a5fa;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:8px}
th{text-align:right;color:#8899bb;font-size:11px;padding:8px;border-bottom:1px solid rgba(255,255,255,.08)}
td{padding:8px;border-bottom:1px solid rgba(255,255,255,.05)}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:10px;font-weight:700}
.b-free{background:#374151;color:#9ca3af}.b-starter{background:#1e3a5f;color:#60a5fa}
.b-pro{background:#312e81;color:#a78bfa}.b-full{background:#14532d;color:#4ade80}
.b-enterprise{background:#7c2d12;color:#fb923c}.b-lifetime{background:#581c87;color:#d8b4fe}
.copy-btn{background:#0f1c30;border:1px solid rgba(255,255,255,.1);color:#60a5fa;padding:4px 10px;border-radius:6px;font-size:11px;cursor:pointer;margin-right:6px}
</style>
</head>
<body>
<div class="wrap">
  <h1>🔐 إدارة عملاء Fiverr</h1>
  <p class="sub">صفحة خاصة بك فقط — إنشاء حسابات جديدة وتغيير الخطط لعملاء OrderFlow</p>

  <div class="card">
    <h2>مفتاح الإدارة</h2>
    <input id="adminKey" type="password" placeholder="ADMIN_API_KEY"/>
  </div>

  <div class="card">
    <h2>➕ إنشاء عميل جديد</h2>
    <label>اسم المستخدم (للدخول)</label>
    <input id="newUsername"/>
    <label>كلمة السر</label>
    <input id="newPassword" type="text"/>
    <label>اسم المتجر</label>
    <input id="newStoreName" placeholder="مثلاً: متجر سارة"/>

    <div style="margin-top:18px;padding-top:14px;border-top:1px solid rgba(255,255,255,.08)">
      <div style="font-size:12px;color:#8899bb;margin-bottom:10px;font-weight:700">⚡ قوالب سريعة — عملاء Fiverr (لا تظهر لهم صفحة الأسعار المحلية)</div>
      <button onclick="createClient('starter','fiverr')" style="background:#2563eb">Fiverr Basic — $35</button>
      <button onclick="createClient('pro','fiverr')" style="background:#7c3aed;margin-right:8px">Fiverr Premium — $85</button>
    </div>

    <div style="margin-top:18px;padding-top:14px;border-top:1px solid rgba(255,255,255,.08)">
      <div style="font-size:12px;color:#8899bb;margin-bottom:10px;font-weight:700">💼 عميل محلي (يشوف صفحة الأسعار كاملة)</div>
      <select id="newPlanLocal">
        <option value="free">Free</option>
        <option value="starter" selected>Starter</option>
        <option value="pro">Pro</option>
        <option value="enterprise">Enterprise</option>
        <option value="lifetime">Lifetime — <span id="lifetimeSlotsDisplay">...</span> متبقي</option>
      </select>
      <button onclick="createClient(document.getElementById('newPlanLocal').value,'local')">إنشاء حساب محلي</button>
    </div>

    <div id="createMsg" class="msg"></div>
    <div id="createResult"></div>
  </div>

  <div class="card">
    <h2>📋 العملاء الحاليون</h2>
    <button onclick="loadClients()" style="margin-top:0">🔄 تحديث القائمة</button>
    <div id="clientsBox"></div>
  </div>
</div>

<script>
// دالة escape إجبارية لكل قيمة نصية قادمة من السيرفر قبل إدراجها بـ innerHTML —
// قبل التعديل كانت القيم تُدرج خام (c.username, c.userId...) مما يفتح XSS مخزّن
// لو احتوى أي اسم مستخدم وسوم HTML/سكربت.
function esc(s){
  return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}

function adminKey(){ return document.getElementById("adminKey").value.trim(); }
function showMsg(id, text, type){
  var el = document.getElementById(id);
  el.className = "msg " + type;
  el.textContent = text;
}

async function createClient(plan, source){
  var key = adminKey();
  if(!key){ showMsg("createMsg","أدخل مفتاح الإدارة أولاً","err"); return; }
  var username = document.getElementById("newUsername").value.trim();
  var password = document.getElementById("newPassword").value.trim();
  var storeName = document.getElementById("newStoreName").value.trim();
  if(!username || !password){ showMsg("createMsg","أدخل اسم المستخدم وكلمة السر","err"); return; }
  try{
    var r = await fetch("/api/admin/createClient", {
      method:"POST",
      headers:{"Content-Type":"application/json","X-Admin-Key":key},
      body: JSON.stringify({username:username, password:password, storeName:storeName, plan:plan, source:source})
    });
    var data = await r.json();
    if(data.status==="ok"){
      showMsg("createMsg","✅ تم إنشاء الحساب بنجاح ("+esc(plan)+" / "+esc(source)+")","ok");
      document.getElementById("createResult").innerHTML =
        '<div class="result-box">'+
          '<div>👤 اسم المستخدم: <code>'+esc(username)+'</code></div>'+
          '<div>🔑 كلمة السر: <code>'+esc(password)+'</code></div>'+
          '<div>🔗 رابط المتجر: <code id="lk">'+esc(data.data.storeLink)+'</code></div>'+
          '<button class="copy-btn" data-copy="'+esc(username+' / '+password)+'">نسخ بيانات الدخول</button>'+
          '<button class="copy-btn" data-copy="'+esc(data.data.storeLink)+'">نسخ رابط المتجر</button>'+
        '</div>';
      document.querySelectorAll('.copy-btn').forEach(function(btn){
        btn.addEventListener('click', function(){ copyText(btn.getAttribute('data-copy')); });
      });
      document.getElementById("newUsername").value = "";
      document.getElementById("newPassword").value = "";
      document.getElementById("newStoreName").value = "";
      loadClients();
    } else {
      showMsg("createMsg","❌ "+data.message,"err");
    }
  }catch(e){ showMsg("createMsg","خطأ فالاتصال بالسيرفر","err"); }
}

function copyText(t){
  navigator.clipboard.writeText(t);
}

async function loadClients(){
  var key = adminKey();
  if(!key){ showMsg("createMsg","أدخل مفتاح الإدارة أولاً","err"); return; }
  var box = document.getElementById("clientsBox");
  box.innerHTML = "⏳ تحميل...";
  try{
    var r = await fetch("/api/admin/listClients", { headers:{"X-Admin-Key":key} });
    var data = await r.json();
    if(data.status!=="ok"){ box.innerHTML = "❌ "+esc(data.message); return; }

    var lifetimeUsed = data.data.filter(function(c){ return c.plan==="lifetime"||c.plan==="full"; }).length;
    var lifetimeLeftEl = document.getElementById("lifetimeSlotsDisplay");
    if(lifetimeLeftEl) lifetimeLeftEl.textContent = Math.max(0, 50-lifetimeUsed);

    if(!data.data.length){ box.innerHTML = "لا يوجد عملاء بعد"; return; }
    var allowedPlans = ["free","starter","pro","enterprise","full","lifetime"];
    box.innerHTML = '<table><thead><tr><th>المستخدم</th><th>ID</th><th>المصدر</th><th>الخطة</th><th>تغيير الخطة</th></tr></thead><tbody>'+
      data.data.map(function(c){
        var srcBadge = c.source==="fiverr" ? '<span class="badge b-pro">Fiverr</span>' : '<span class="badge b-starter">محلي</span>';
        var safePlan = allowedPlans.indexOf(c.plan) !== -1 ? c.plan : "free";
        return '<tr><td>'+esc(c.username)+'</td><td style="font-size:10px;color:#8899bb">'+esc(c.userId)+'</td>'+
          '<td>'+srcBadge+'</td>'+
          '<td><span class="badge b-'+safePlan+'">'+esc(String(c.plan).toUpperCase())+'</span></td>'+
          '<td><select class="plan-select" data-uid="'+esc(c.userId)+'" data-uname="'+esc(c.username)+'">'+
            allowedPlans.map(function(p){
              return '<option value="'+p+'"'+(p===safePlan?" selected":"")+'>'+p+'</option>';
            }).join("")+
          '</select></td></tr>';
      }).join("")+
      '</tbody></table>';
    document.querySelectorAll('.plan-select').forEach(function(sel){
      sel.addEventListener('change', function(){
        changePlan(sel.getAttribute('data-uid'), sel.getAttribute('data-uname'), sel.value);
      });
    });
  }catch(e){ box.innerHTML = "خطأ فالاتصال"; }
}

async function changePlan(userId, username, plan){
  var key = adminKey();
  try{
    var r = await fetch("/api/updateUserPlan", {
      method:"POST",
      headers:{"Content-Type":"application/json","X-Admin-Key":key},
      body: JSON.stringify({userId:userId, username:username, plan:plan})
    });
    var data = await r.json();
    if(data.status==="ok") loadClients();
    else alert("❌ "+data.message);
  }catch(e){ alert("خطأ فالاتصال"); }
}
</script>
</body>
</html>""", 200


@app.route("/api/updateUserPlan", methods=["POST"])
@require_admin
def api_update_user_plan():
    body     = request.get_json(silent=True) or {}
    uid      = str(body.get("userId")   or "").strip()
    username = str(body.get("username") or "").strip()
    plan     = str(body.get("plan")     or "starter").strip().lower()
    if not uid or not username: return err_json("Missing fields")
    if plan not in PLANS: return err_json(f"Invalid plan: {list(PLANS.keys())}")
    existing = _fb_get(f"users/{username}") or {}
    was_lifetime = str(existing.get("plan", "")).lower() in _LIFETIME_PLANS
    existing["plan"]         = plan
    existing["plan_updated"] = time.strftime("%Y-%m-%d %H:%M")
    _fb_put(f"users/{username}", existing)
    # عدّاد lifetime يتبع الانتقال من/إلى lifetime/full (lifetime↔full ما يبدّلوش)
    now_lifetime = plan in _LIFETIME_PLANS
    if was_lifetime != now_lifetime:
        try:
            _adjust_lifetime_counter(1 if now_lifetime else -1)
        except Exception as e:
            logging.error(f"lifetime counter update failed: {type(e).__name__} — شغّل rebuildIndexes")
    return ok_json({"plan": plan})

@app.route("/api/admin/createClient", methods=["POST"])
@require_admin
def api_admin_create_client():
    body     = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    store_name = str(body.get("storeName") or "").strip() or "متجري"
    plan     = str(body.get("plan") or "starter").strip().lower()
    source   = str(body.get("source") or "local").strip().lower()
    if source not in ("local", "fiverr"): source = "local"
    if not username or not password: return err_json("اسم المستخدم وكلمة السر مطلوبين")
    if len(password) < 6: return err_json("كلمة السر قصيرة جداً (6 أحرف على الأقل)")
    if plan not in PLANS: return err_json(f"خطة غير صحيحة: {list(PLANS.keys())}")
    if _username_taken(username): return err_json("اسم المستخدم مستعمل من قبل", 409)
    if plan in _LIFETIME_PLANS:
        # حجز خانة lifetime ذرّياً قبل إنشاء الحساب (بدل عدّ /users كاملة)
        try:
            _adjust_lifetime_counter(1, cap=LIFETIME_MAX_SLOTS)
        except _LifetimeFull:
            return err_json(f"تم الوصول للحد الأقصى ({LIFETIME_MAX_SLOTS}) من عروض Lifetime", 409)
        except Exception as e:
            logging.error(f"lifetime counter reserve failed: {type(e).__name__}")
            return err_json("Firebase unavailable", 503)
    new_uid = str(int(time.time() * 1000))
    if not _fb_put(f"users/{username}", {
        "Username": username, "Password": _hash_password(password),
        "User_ID": new_uid, "plan": plan, "source": source,
        "plan_updated": time.strftime("%Y-%m-%d %H:%M"),
    }):
        if plan in _LIFETIME_PLANS:
            try: _adjust_lifetime_counter(-1)
            except Exception: pass
        return err_json("Firebase unavailable", 503)
    _fb_put(f"uid_index/{new_uid}", username)
    _fb_put(f"uname_index/{_uname_key(username)}", username)
    _fb_put(f"data/{new_uid}/storeSettings", {
        "name": store_name, "tagline": "", "logo": "🛒", "lang": "AR", "currency": "DZD",
    })
    return ok_json({"username": username, "userId": new_uid,
                     "storeLink": f"{request.url_root.rstrip('/')}/?store={new_uid}"})

@app.route("/api/admin/rebuildIndexes", methods=["POST"])
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


@app.route("/api/admin/listClients", methods=["GET"])
@require_admin
def api_admin_list_clients():
    users = _fb_get("users") or {}
    result = []
    for uname, u in users.items():
        if isinstance(u, dict):
            result.append({
                "username": u.get("Username", uname), "userId": u.get("User_ID", ""),
                "plan": u.get("plan", "starter"), "planUpdated": u.get("plan_updated", ""),
                "source": u.get("source", "local"),
            })
    result.sort(key=lambda x: x.get("planUpdated",""), reverse=True)
    return ok_json(result)

# ── /api/saas ─────────────────────────────────────────────
# مسارات محمية تحت data/{uid}/ لا يُسمح بلمسها عبر أفعال firebaseGet/Set/Update/Push
# العامة أدناه — لأن لها منطق تحقق خاص (صلاحيات الخطة، الحدود الشهرية، فحوصات SSRF...)
# ضمن endpoints مخصصة (landing/generate, woo/connect, إلخ).


@app.route("/api/saas", methods=["POST","OPTIONS"])
def api_saas():
    if request.method == "OPTIONS": return jsonify({}), 200
    token   = _extract_bearer(request)
    auth    = decode_token(token) if token else None
    if not auth or not auth.get("uid"):
        return err_json("Unauthorized", 401)
    auth_uid      = auth["uid"]
    auth_username = auth.get("username", "")
    auth_role     = auth.get("role", "owner")
    auth_perms    = auth.get("perms", {}) or {}

    payload = request.get_json(silent=True) or {}
    action  = str(payload.get("action") or "").strip()
    if not action: return err_json("missing_action")
    def _path_allowed(path):
        # المقاطع الفارغة تتحذف كيما يدير Firebase — قبل: "data/{uid}//usage" كان يدوز
        # الفحص (SEC-010)، و"data/{uid}/" كان يسمح بالكتابة فوق شجرة التاجر كاملة.
        # orders/stats/customers/ratings ممنوعين: المجاميع الجارية تتحدّث غير من المسارات
        # المخصصة، وكتابة مباشرة كانت تخليهم غالطين.
        segs = [s for s in str(path or "").split("/") if s]
        blocked_segments = {"usage", "integrations", "landingPages", "teamMembers",
                            "orders", "stats", "customers", "ratings"}
        if len(segs) >= 3 and segs[0] == "data" and segs[1] == str(auth_uid):
            return segs[2] not in blocked_segments
        return len(segs) >= 2 and segs[0] == "ai_logs" and segs[1] == str(auth_uid)

    if action in ("firebaseGet", "firebaseSet", "firebaseUpdate", "firebasePush") and auth_role == "member":
        return err_json("غير مسموح لعضو الفريق باستعمال هذا المسار", 403)
    if action in ("getBotLogs", "updateBotSettings") and auth_role == "member" and not auth_perms.get("bot"):
        return err_json("ليس لديك صلاحية الوصول لهذا القسم", 403)

    try:
        if action == "firebaseGet":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            return ok_json(_fb_get(payload["path"]))
        if action == "firebaseSet":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            value = payload.get("payload", payload.get("data"))
            # firebase-admin يرفض set(None) — قبل، _fb_put كان يفشل بصمت والرد يقول ok
            if value is None: return err_json("set requires a value")
            if not _fb_put(payload["path"], value): return err_json("write failed", 500)
            return ok_json(True)
        if action == "firebaseUpdate":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            data = payload.get("payload", payload.get("data"))
            if not isinstance(data, dict): return err_json("update requires object")
            _fb_patch(payload["path"], data)
            return ok_json(True)
        if action == "firebasePush":
            if not _path_allowed(payload.get("path","")): return err_json("Forbidden path", 403)
            return ok_json({"key": _fb_push(payload["path"], payload.get("payload", payload.get("data")))})
        if action == "getBotLogs":
            limit = max(1, min(int(payload.get("limit") or 200), 500))
            found = _fb_query(f"bot_logs/{auth_uid}", "timestamp", limit_last=limit)
            if found is None:
                return err_json("تعذّر تحميل السجل — حاول بعد قليل", 503)
            items = [dict(v, id=k) for k, v in found.items() if isinstance(v, dict)]
            items.sort(key=lambda x: x.get("timestamp", 0) or 0, reverse=True)
            return ok_json(items)
        if action == "updateBotSettings":
            if not auth_username: return err_json("missing_username")
            data = payload.get("payload", payload.get("data")) or {}
            data = _sanitize_bot_settings_patch(data)
            if not data:
                return ok_json(True)
            return _save_bot_settings(auth_username, auth_uid, data)
        return err_json("unknown_action")
    except Exception as e:
        logging.error(f"/api/saas: {e}")
        return err_json(str(e), 500)


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp
@app.before_request
def limit_size():
    if request.content_length and request.content_length > MAX_PAYLOAD_SIZE:
        abort(413)


# ── Blueprints: routes/ (مسارات منقولة من app.py فـ Phase 4) — قبل features/
from routes.public import (
    serve_index,
    healthz,
    _health_cache,
    _HEALTH_TTL,
    health,
    privacy_page,
    terms_redirect,
    api_add_order,
    _compute_store_products,
    api_get_store_products,
    api_track_order,
    api_submit_rating,
    api_get_product_ratings,
    api_get_store_cities,
    api_get_store_settings,
    landing_page_public_view,
)
from routes.oauth import (
    _OAUTH_FAIL_MSG,
    _OAUTH_STATE_BAD_MSG,
    _OAUTH_COOKIE,
    _OAUTH_STATE_TTL,
    _nonce_hash,
    _NonceRejected,
    _consume_oauth_nonce,
    fb_oauth_callback,
    _fb_oauth_callback_page,
    _js_str,
    _post_to_opener_js,
    _oauth_error_page,
    api_get_oauth_state,
    fb_status,
    fb_disconnect,
)
from routes.webhook import (
    webhook,
)
import routes.public as _routes_public
import routes.oauth as _routes_oauth
import routes.webhook as _routes_webhook
app.register_blueprint(_routes_public.bp)
app.register_blueprint(_routes_oauth.bp)
app.register_blueprint(_routes_webhook.bp)

from routes.auth import (
    api_login,
    api_me,
    api_team_list_members,
    api_team_add_member,
    api_team_update_member,
    api_team_delete_member,
)
from routes.orders import (
    _ORDERS_PAGE_MAX,
    _ORDERS_CURSOR_MARGIN_MS,
    api_get_orders,
    api_update_status,
    api_update_order_delivery,
)
from routes.catalog import (
    api_get_products,
    api_add_product,
    api_delete_product,
    api_get_cities,
    api_add_city,
    api_delete_city,
    api_get_customers,
    api_get_dashboard,
)
from routes.store import (
    _STORE_TEXT_LIMITS,
    _STORE_CURRENCIES,
    _clean_store_setting,
    api_update_store_settings,
    api_landing_questions,
    api_landing_generate,
    api_landing_list,
    api_landing_toggle_publish,
    api_landing_delete,
    api_landing_post_instagram,
    _detect_image_kind,
    api_upload_image,
)
from routes.integrations import (
    api_woo_connect,
    api_woo_status,
    api_woo_disconnect,
    api_woo_sync,
)
from routes.messaging import (
    api_get_bot_settings,
    api_update_bot_settings,
    api_get_conversations,
    api_get_conversation_messages,
    api_send_message,
)
from routes.account import (
    api_get_user_plan,
    api_recalc_stats,
)
import routes.auth as _routes_auth
import routes.orders as _routes_orders
import routes.catalog as _routes_catalog
import routes.store as _routes_store
import routes.integrations as _routes_integrations
import routes.messaging as _routes_messaging
import routes.account as _routes_account
app.register_blueprint(_routes_auth.bp)
app.register_blueprint(_routes_orders.bp)
app.register_blueprint(_routes_catalog.bp)
app.register_blueprint(_routes_store.bp)
app.register_blueprint(_routes_integrations.bp)
app.register_blueprint(_routes_messaging.bp)
app.register_blueprint(_routes_account.bp)

from features.discounts_api import discounts_bp
from features.tracking_api import tracking_bp
from features.support_api import support_bp
from features.shipping_api import shipping_bp
from features.assistant_api import assistant_bp
from features.multistore_api import multistore_bp

app.register_blueprint(discounts_bp)
app.register_blueprint(tracking_bp)
app.register_blueprint(support_bp)
app.register_blueprint(shipping_bp)
app.register_blueprint(assistant_bp)
app.register_blueprint(multistore_bp)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)