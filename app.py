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


# ── Auth ──────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
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

@app.route("/api/me", methods=["GET"])
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
@app.route("/api/team/listMembers", methods=["GET"])
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

@app.route("/api/team/addMember", methods=["POST"])
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

@app.route("/api/team/updateMember", methods=["POST"])
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

@app.route("/api/team/deleteMember", methods=["POST"])
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


_ORDERS_PAGE_MAX         = 500
_ORDERS_CURSOR_MARGIN_MS = 30_000  # تداخل آمن: كتابة بطيئة (retry) ما تضيعش من الـ polling


@app.route("/api/getOrders", methods=["GET"])
@require_auth
@require_perm("orders")
def api_get_orders():
    """قبل: كل طلبات التاجر فكل نداء (والواجهة تنادي كل 8 ثواني). دابا باستعلامات مفهرسة:
    - بلا معاملات: آخر `limit` طلب (افتراضياً 200) حسب createdAt.
    - before=<createdAt>: الصفحة الأقدم ("تحميل الأقدم").
    - since=<cursor>: غير الطلبات اللي تبدّلت (updatedAt >= cursor). reset=true إذا كثار بزاف.
    - createdAfter=<ms>: الطلبات الجديدة من تاريخ (منحنى الأرباح).
    data تبقى لائحة (الأحدث أولاً)؛ cursor وhasMore فنفس الرد."""
    uid  = request.auth_uid
    path = f"data/{uid}/orders"
    try:
        limit         = max(1, min(int(request.args.get("limit") or 200), _ORDERS_PAGE_MAX))
        since         = _opt_int_arg("since")
        before        = _opt_int_arg("before")
        created_after = _opt_int_arg("createdAfter")
    except ValueError:
        return err_json("Invalid paging parameters")
    started = _orders_svc._now_ms()
    if since is not None:
        cap   = _ORDERS_PAGE_MAX
        found = _fb_query(path, "updatedAt", start_at=since, limit_last=cap + 1)
    elif created_after is not None:
        cap   = _ORDERS_PAGE_MAX
        found = _fb_query(path, "createdAt", start_at=created_after, limit_last=cap + 1)
    else:
        cap   = limit
        found = _fb_query(path, "createdAt", end_at=(before - 1) if before is not None else None,
                          limit_last=cap + 1)
    if found is None:
        return err_json("تعذّر تحميل الطلبات — حاول بعد قليل", 503)
    orders   = [o for o in found.values() if isinstance(o, dict)]
    has_more = len(orders) > cap
    if has_more:
        orders = orders[-cap:]  # النتائج تصاعدية → نخلّيو الأحدث
    orders.sort(key=lambda o: o.get("createdAt") or 0, reverse=True)
    body = {"status": "ok", "data": orders, "hasMore": has_more,
            "cursor": started - _ORDERS_CURSOR_MARGIN_MS}
    if since is not None and has_more:
        body["reset"] = True  # تبدّلات أكثر من الحد — الواجهة تعاود التحميل من الأول
    return jsonify(body)


@app.route("/api/updateStatus", methods=["POST"])
@require_auth
@require_perm("orders")
def api_update_status():
    body   = request.get_json(silent=True) or {}
    uid    = request.auth_uid
    oid    = str(body.get("orderId") or "").strip()
    status = str(body.get("status")  or "").strip()
    if not oid or not status: return err_json("Missing fields")
    order = _fb_get(f"data/{uid}/orders/{oid}")
    if not order: return err_json("Order not found", 404)
    before = dict(order)
    order["status"] = status
    profit = 0
    now    = time.strftime("%Y-%m-%d %H:%M")
    delivery_type = order.get("deliveryType") or "home"
    if status == "Confirmed" and not order.get("date_sent"):
        order["date_sent"] = now
    if status == "Delivered" and not order.get("date_delivered"):
        order["date_delivered"] = now
    if status in ("Confirmed", "Refused", "Delivered"):
        p_data = _fb_get(f"data/{uid}/products/{order.get('product')}")
        c_data = _fb_get(f"data/{uid}/cities/{order.get('city')}")
        if p_data and c_data:
            profit = _calc_order_profit(p_data, c_data, order.get("qty", 1), delivery_type, status, order.get("profit", 0))
    order["profit"] = profit
    _save_order(uid, oid, order, before=before)
    log_audit_entry(uid, request.auth_member_username or "owner",
                     "تغيير حالة طلب", f"الطلب {oid} → {status}")
    return ok_json(True)

@app.route("/api/updateOrderDelivery", methods=["POST"])
@require_auth
@require_perm("orders")
def api_update_order_delivery():
    body  = request.get_json(silent=True) or {}
    uid   = request.auth_uid
    oid   = str(body.get("orderId") or "").strip()
    dtype = str(body.get("deliveryType") or "").strip()
    if not oid or dtype not in ("home", "desk"):
        return err_json("Missing or invalid fields")
    order = _fb_get(f"data/{uid}/orders/{oid}")
    if not order: return err_json("Order not found", 404)
    before = dict(order)
    order["deliveryType"] = dtype
    p_data = _fb_get(f"data/{uid}/products/{order.get('product')}")
    c_data = _fb_get(f"data/{uid}/cities/{order.get('city')}")
    if p_data and c_data:
        ship_cust, _ = _ship_values(c_data, dtype)
        order["total"]  = (float(p_data.get("sell", 0)) * int(order.get("qty", 1))) + ship_cust
        order["profit"] = _calc_order_profit(p_data, c_data, order.get("qty", 1), dtype, order.get("status",""), order.get("profit", 0))
    _save_order(uid, oid, order, before=before)
    return ok_json(True)

# ── Products ──────────────────────────────────────────────
@app.route("/api/getProducts", methods=["GET"])
@require_auth
@require_perm("products")
def api_get_products():
    uid = request.auth_uid
    # sold/available/stat من stats.sales (بدل القيم المخزّنة اللي كانت تتحدّث غير عند Confirmed)
    sold = _sold_by_name(_get_stats(uid))
    products = []
    for p in _fb_list(f"data/{uid}/products"):
        if isinstance(p, dict):
            p = {**p, **_stock_fields(p, sold.get(p.get("name", ""), 0))}
        products.append(p)
    return ok_json(products)


@app.route("/api/addProduct", methods=["POST"])
@require_auth
@require_perm("products")
def api_add_product():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    if not d or not d.get("name"): return err_json("Missing fields")
    name     = d["name"]
    existing = _fb_get(f"data/{uid}/products/{name}") or {}
    merged   = {**existing, "name": name,
        "category":    d.get("category",    existing.get("category",    "")),
        "size":        d.get("size",        existing.get("size",        "")),
        "colors":      d.get("colors",      existing.get("colors",      "")),
        "cost":        float(d.get("cost",  existing.get("cost",        0))),
        "sell":        float(d.get("sell",  existing.get("sell",        0))),
        "init":        int(d.get("init",    existing.get("init",        0))),
        "description": d.get("description", existing.get("description", "")),
        "visible":     d.get("visible",     existing.get("visible",     "yes")),
        "image":       d.get("image",       existing.get("image",       "")),
        "images":      d.get("images",      existing.get("images",      [])),
    }
    if not existing:
        merged["sold"]       = 0
        merged["available"]  = int(d.get("init", 0))
        merged["created_at"] = time.time()
        av = merged["available"]
        merged["stat"] = ("Out of Stock" if av <= 0 else "Low Stock" if av <= LOW_STOCK_THRESHOLD else "In Stock")
    _fb_put(f"data/{uid}/products/{name}", merged)
    return ok_json(True)

@app.route("/api/deleteProduct", methods=["POST"])
@require_auth
@require_perm("products")
def api_delete_product():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    name = str(d.get("name") or "").strip()
    if not name: return err_json("Missing fields")
    _fb_delete(f"data/{uid}/products/{name}")
    log_audit_entry(uid, request.auth_member_username or "owner", f"حذف منتج {name}")
    return ok_json(True)


# ── Cities ────────────────────────────────────────────────
@app.route("/api/getCities", methods=["GET"])
@require_auth
@require_perm("cities")
def api_get_cities():
    uid    = request.auth_uid
    raw    = _fb_get(f"data/{uid}/cities") or {}
    cities = []
    for k, v in raw.items():
        if isinstance(v, dict):
            v["name"] = v.get("name", k)
            cities.append(v)
    return ok_json(cities)


@app.route("/api/addCity", methods=["POST"])
@require_auth
@require_perm("cities")
def api_add_city():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    name = str(d.get("name") or "").strip()
    if not name: return err_json("Missing fields")
    if len(name) > 100: return err_json("اسم المدينة طويل جداً")
    _fb_put(f"data/{uid}/cities/{name}", {
        "name": name,
        "costShip": float(d.get("costShip",0)), "custShip": float(d.get("custShip",0)),
        "deskCost": float(d.get("deskCost",0)), "deskCust": float(d.get("deskCust",0)),
        "returnFee": float(d.get("returnFee",0)),
    })
    return ok_json(True)
@app.route("/api/deleteCity", methods=["POST"])
@require_auth
@require_perm("cities")
def api_delete_city():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    name = str(body.get("name") or "").strip()
    if not name: return err_json("Missing fields")
    _fb_delete(f"data/{uid}/cities/{name}")
    return ok_json(True)
# ── Customers ─────────────────────────────────────────────
@app.route("/api/getCustomers", methods=["GET"])
@require_auth
@require_perm("customers")
def api_get_customers():
    """من data/{uid}/customers (مجموع لكل رقم) — بدل تنزيل كل الطلبات."""
    uid = request.auth_uid
    raw = _fb_get(f"data/{uid}/customers") or {}
    result = []
    for ph, c in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(c, dict): continue
        stats = {"confirmed": 0, "refused": 0, "delivered": 0, **(c.get("stats") or {})}
        ref = stats["refused"]
        con = stats["confirmed"] + stats["delivered"]
        rating = "Bad" if ref >= BAD_CUSTOMER_THRESHOLD else "Good" if con >= 3 and ref == 0 else "Neutral"
        result.append({"name": c.get("name", ""), "phone": c.get("phone", ""), "city": c.get("city", ""),
                       "totalOrders": c.get("totalOrders", 0), "stats": stats, "type": rating})
    return ok_json(result)

# ── Dashboard ─────────────────────────────────────────────
@app.route("/api/getDashboard", methods=["GET"])
@require_auth
def api_get_dashboard():
    """من data/{uid}/stats + المنتجات — بدل تنزيل كل الطلبات فكل فتحة للوحة."""
    uid = request.auth_uid
    stats        = _get_stats(uid)
    products_raw = _fb_get(f"data/{uid}/products") or {}
    tot       = _safe_int(stats.get("total"))
    conf      = _safe_int(stats.get("confirmed"))
    ref       = _safe_int(stats.get("refused"))
    delivered = _safe_int(stats.get("delivered"))
    profit    = _safe_int(stats.get("profitCents")) / 100
    sales     = _sold_by_name(stats)
    top_products = sorted([{"name": k, "qty": v} for k, v in sales.items()],
                          key=lambda x: (-x["qty"], x["name"]))[:5]
    low_stock = []
    for p in products_raw.values():
        if not isinstance(p, dict): continue
        remaining = _safe_int(p.get("init", 0)) - sales.get(p.get("name", ""), 0)
        if remaining <= LOW_STOCK_THRESHOLD:
            low_stock.append({"name": p.get("name", ""), "rem": remaining,
                              "stat": "Out of Stock" if remaining <= 0 else "Low Stock"})
    return ok_json({"totalOrders": tot, "confirmed": conf, "refused": ref, "delivered": delivered,
                    "totalProfit": round(profit, 2), "confirmRate": round(conf/tot*100) if tot else 0,
                    "refuseRate": round(ref/tot*100) if tot else 0,
                    "topProducts": top_products, "lowStock": low_stock})


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

@app.route("/api/updateStoreSettings", methods=["POST"])
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


@app.route("/api/landing/questions", methods=["POST"])
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

@app.route("/api/landing/generate", methods=["POST"])
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

@app.route("/api/landing/list", methods=["GET"])
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

@app.route("/api/landing/togglePublish", methods=["POST"])
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

@app.route("/api/landing/delete", methods=["POST"])
@require_auth
@require_perm("landing")
def api_landing_delete():
    body    = request.get_json(silent=True) or {}
    uid     = request.auth_uid
    page_id = str(body.get("pageId") or "").strip()
    if not page_id: return err_json("Missing pageId")
    _fb_delete(f"data/{uid}/landingPages/{page_id}")
    return ok_json(True)

@app.route("/api/landing/postToInstagram", methods=["POST"])
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


# ── WooCommerce Integration ───────────────────────────────
@app.route("/api/woo/connect", methods=["POST"])
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

@app.route("/api/woo/status", methods=["GET"])
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

@app.route("/api/woo/disconnect", methods=["POST"])
@require_auth
@require_perm("integrations")
def api_woo_disconnect():
    uid = request.auth_uid
    _fb_delete(f"data/{uid}/integrations/woocommerce")
    return ok_json(True)

@app.route("/api/woo/sync", methods=["POST"])
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

@app.route("/api/uploadImage", methods=["POST"])
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

# ── Bot Settings ──────────────────────────────────────────
@app.route("/api/getBotSettings", methods=["GET"])
@require_auth
@require_perm("bot")
def api_get_bot_settings():
    username = request.auth_username
    data = _fb_get(f"users/{username}") or {}
    safe = {k: v for k, v in data.items() if k != "Password"}
    return ok_json(safe)

@app.route("/api/updateBotSettings", methods=["POST"])
@require_auth
@require_perm("bot")
def api_update_bot_settings():
    body     = request.get_json(silent=True) or {}
    uid      = request.auth_uid
    username = request.auth_username
    d        = body.get("data") or {}
    if not username: return err_json("Missing fields")
    # حماية Mass Assignment: نستثني الحقول الحساسة (plan/source/Password/User_ID/Username)
    # قبل الدمج — هذا المسار مخصص فقط لإعدادات البوت وليس لبيانات الحساب/الخطة.
    d = _sanitize_bot_settings_patch(d)
    return _save_bot_settings(username, uid, d)


# ── Conversations / Messages ───────────────────────────────
@app.route("/api/getConversations", methods=["GET"])
@require_auth
@require_perm("messages")
def api_get_conversations():
    """قبل: كل conversations_meta/{uid} فكل نداء (الواجهة كل 10 ثواني). دابا (lastTimestamp مفهرس):
    - بلا معاملات: آخر `limit` محادثة (افتراضياً 50).
    - before=<lastTimestamp>: الصفحة الأقدم.
    - since=<cursor>: غير المحادثات اللي تحرّكت (reset=true إذا كثار بزاف).
    data الأحدث أولاً، مع cursor (وقت السيرفر بالثواني ناقص 30) وhasMore."""
    uid = request.auth_uid
    path = f"conversations_meta/{uid}"
    try:
        limit  = max(1, min(int(request.args.get("limit") or 50), 200))
        since  = _opt_float_arg("since")
        before = _opt_float_arg("before")
    except ValueError:
        return err_json("Invalid paging parameters")
    started = time.time()
    if since is not None:
        cap, found = 200, _fb_query(path, "lastTimestamp", start_at=since, limit_last=201)
    else:
        cap = limit
        found = _fb_query(path, "lastTimestamp", end_at=before, limit_last=limit + 2)
    if found is None:
        return err_json("تعذّر تحميل المحادثات — حاول بعد قليل", 503)
    result = []
    for sender_id, m in found.items():
        if not isinstance(m, dict): continue
        if before is not None and (m.get("lastTimestamp") or 0) >= before: continue
        result.append({
            "senderId": sender_id, "platform": m.get("platform",""),
            "lastMessage": m.get("lastMessage",""), "lastTimestamp": m.get("lastTimestamp",0),
            "lastDirection": m.get("lastDirection",""), "name": m.get("name","") or sender_id,
        })
    has_more = len(result) > cap
    if has_more:
        result = result[-cap:]  # تصاعدي → نخلّيو الأحدث
    result.sort(key=lambda x: x.get("lastTimestamp",0) or 0, reverse=True)
    body = {"status": "ok", "data": result, "hasMore": has_more, "cursor": started - 30}
    if since is not None and has_more:
        body["reset"] = True
    return jsonify(body)


@app.route("/api/getConversationMessages", methods=["GET"])
@require_auth
@require_perm("messages")
def api_get_conversation_messages():
    uid = request.auth_uid
    sender_id = request.args.get("senderId","").strip()
    if not sender_id: return err_json("Missing senderId")
    # مفاتيح push مرتّبة زمنياً → order_by_key بلا فهرس. after/before = مفتاح رسالة
    try:
        limit = max(1, min(int(request.args.get("limit") or 100), 300))
    except ValueError:
        return err_json("Invalid paging parameters")
    after  = request.args.get("after", "").strip() or None
    before = request.args.get("before", "").strip() or None
    path = f"conversations/{uid}/{sender_id}"
    if after:
        found = _fb_query(path, "$key", start_at=after, limit_last=301)
    else:
        found = _fb_query(path, "$key", end_at=before, limit_last=limit + 2)
    if found is None:
        return err_json("تعذّر تحميل الرسائل — حاول بعد قليل", 503)
    items = []
    for k, v in found.items():
        if k in (after, before) or not isinstance(v, dict):
            continue
        row = dict(v); row["id"] = k
        items.append(row)
    has_more = False
    if not after and len(items) > limit:
        items, has_more = items[-limit:], True
    return jsonify({"status": "ok", "data": items, "hasMore": has_more})

@app.route("/api/sendMessage", methods=["POST"])
@require_auth
@require_perm("messages")
def api_send_message():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    sender_id = str(body.get("senderId") or "").strip()
    text      = str(body.get("text") or "").strip()
    if not sender_id or not text:
        return err_json("Missing fields")
    if not PLANS.get(get_user_plan(uid), {}).get("bot", False):
        return err_json("هذه الميزة تتطلب خطة Pro أو أعلى", 403)
    meta = _fb_get(f"conversations_meta/{uid}/{sender_id}") or {}
    platform = meta.get("platform","fb")
    page_id  = meta.get("pageId","")
    if not meta:
        return err_json("لا توجد محادثة سابقة مع هذا العميل — لا يمكن بدء محادثة جديدة بسبب قيود ميتا", 404)
    bot_settings = _fb_get(f"users/{request.auth_username}") or {}
    ok = False
    if platform == "wa":
        token = str(bot_settings.get("whtsapp_token") or "").strip()
        phone_number_id = page_id or str(bot_settings.get("phone_number_id") or "").strip()
        if not token or not phone_number_id:
            return err_json("إعدادات واتساب غير مكتملة")
        ok = send_whatsapp_message(phone_number_id, sender_id, text, token)
    elif platform == "ig":
        token  = str(bot_settings.get("instgram_access_token") or "").strip()
        fb_pid = page_id or str(bot_settings.get("page_id_FB") or "").strip()
        if not token:
            return err_json("إعدادات إنستغرام غير مكتملة")
        ok = send_facebook_message(sender_id, text, token, page_id=(fb_pid or None))
    else:
        token  = str(bot_settings.get("fb_access_token") or "").strip()
        fb_pid = page_id or str(bot_settings.get("page_id_FB") or "").strip()
        if not token:
            return err_json("إعدادات فيسبوك غير مكتملة")
        ok = send_facebook_message(sender_id, text, token, page_id=(fb_pid or None))
    if not ok:
        return err_json("فشل إرسال الرسالة — تحقق من اتصال Facebook/Instagram/WhatsApp", 502)
    _log_conversation(uid, sender_id, "out", text, platform, via="manual", page_id=page_id)
    return ok_json(True)

# ── Plans / Subscriptions ─────────────────────────────────
@app.route("/api/getUserPlan", methods=["GET"])
@require_auth
def api_get_user_plan():
    uid      = request.auth_uid
    user_rec = _get_user_record(uid)
    plan     = str(user_rec.get("plan", "starter")).lower()
    source   = str(user_rec.get("source", "local")).lower()
    currency = (_fb_get(f"data/{uid}/storeSettings/currency") or "DZD")
    plan_features = PLANS.get(plan, PLANS["starter"])
    usage = {}
    if plan_features.get("orderCap"):
        usage["orders"]  = {"used": _get_usage(uid, "orderCount"),  "cap": plan_features["orderCap"]}
    if plan_features.get("botMsgCap"):
        usage["botMsgs"] = {"used": _get_usage(uid, "botMsgCount"), "cap": plan_features["botMsgCap"]}
    lifetime_left = max(0, LIFETIME_MAX_SLOTS - _count_lifetime_accounts()) if source == "local" else None
    return ok_json({"plan": plan, "features": plan_features, "currency": currency,
                     "source": source, "lifetimeSlotsLeft": lifetime_left,
                     "botLaunched": BOT_LAUNCHED, "usage": usage,
                     "role": getattr(request, "auth_role", "owner"),
                     "teamCount": _count_team_members(uid)})

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


@app.route("/api/recalcStats", methods=["POST"])
@require_auth
@require_owner
def api_recalc_stats():
    """إصلاح يدوي للمجاميع (إذا انقطع شي حاجة بين كتابة طلب وتحديث المجموع): حساب كامل
    من كل الطلبات. مرة فـ 10 دقائق لكل تاجر — قراءة كاملة غالية."""
    uid = request.auth_uid
    if _login_rate_limited(f"recalc:{uid}", max_attempts=1, window=600):
        return err_json("تمت إعادة الحساب مؤخراً — حاول بعد 10 دقائق", 429)
    res = _recompute_aggregates(uid)
    if res is None:
        return err_json("Firebase unavailable", 503)
    return ok_json(res)


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