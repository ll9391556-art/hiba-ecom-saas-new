# -*- coding: utf-8 -*-
"""لوحة الإدارة (/admin) ومسارات X-Admin-Key: الخطط، إنشاء العملاء، التعبئة (rebuildIndexes)، اللائحة. منقول من app.py بلا تغيير (Phase 4 / A8)."""
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

from core.config import (
    LIFETIME_MAX_SLOTS,
    PLANS,
)
from core.db import (
    _fb_get,
    _fb_keys,
    _fb_put,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _hash_password,
    require_admin,
)
from services.bot import (
    _migrate_bot_logs,
)
from services.orders import (
    _rebuild_order_fields,
    _recompute_aggregates,
)
from services.users import (
    _LIFETIME_PLANS,
    _LifetimeFull,
    _adjust_lifetime_counter,
    _rebuild_user_indexes,
    _uname_key,
    _username_taken,
)

bp = Blueprint("admin", __name__)




@bp.route("/admin", methods=["GET"])
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


@bp.route("/api/updateUserPlan", methods=["POST"])
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


@bp.route("/api/admin/createClient", methods=["POST"])
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


@bp.route("/api/admin/rebuildIndexes", methods=["POST"])
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


@bp.route("/api/admin/listClients", methods=["GET"])
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
