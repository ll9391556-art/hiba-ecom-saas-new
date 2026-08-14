import os
import json
import hmac
import hashlib
import logging
import requests
import time
import re
import threading
import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken
from functools import wraps
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, abort, jsonify, send_from_directory
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db, storage as fb_storage
from google import genai
from google.genai import types
from time import sleep

app = Flask(__name__, static_folder="static")
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", force=True)

_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="bot_worker")

MAX_PAYLOAD_SIZE       = 2 * 1024 * 1024
VERIFY_TOKEN           = os.environ.get("VERIFY_TOKEN",    "HEBA_SAAS_2026").strip()
META_APP_SECRET        = os.environ.get("META_APP_SECRET", "").strip()
MAX_HISTORY_TURNS      = 10
LOW_STOCK_THRESHOLD    = 5
BAD_CUSTOMER_THRESHOLD = 3
_JSON_START            = "###JSON_START###"
_JSON_END              = "###JSON_END###"

_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

FB_DB_URL           = os.environ.get("FB_DB_URL",    "https://saas-order-default-rtdb.europe-west1.firebasedatabase.app").strip()
# ملاحظة: لم نعد نستعمل FB_DB_SECRET — كل عمليات القاعدة تمر الآن عبر Firebase Admin SDK
# (FIREBASE_CREDENTIALS) كما توصي به Firebase نفسها بدل الأسرار القديمة (Legacy Secrets).
FB_APP_ID           = os.environ.get("FB_APP_ID",    "1484940433173462").strip()
FB_APP_SECRET_OAUTH = os.environ.get("FB_APP_SECRET","").strip()
REDIRECT_URI        = os.environ.get("REDIRECT_URI", "https://orderconfidence.com/callback").strip()
FB_STORAGE_BUCKET   = os.environ.get("FB_STORAGE_BUCKET", "saas-order.firebasestorage.app").strip()

# ── Auth (JWT) ────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
if not JWT_SECRET:
    JWT_SECRET = "INSECURE_DEV_SECRET_CHANGE_ME_NOW"
    logging.warning("⚠️ JWT_SECRET غير مضبوط بالبيئة — يتم استخدام قيمة افتراضية غير آمنة. اضبط JWT_SECRET في الإنتاج فوراً!")
JWT_ALGO         = "HS256"
JWT_EXPIRY_HOURS = 24 * 7  # صلاحية الجلسة: 7 أيام

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
if not ADMIN_API_KEY:
    logging.warning("⚠️ ADMIN_API_KEY غير مضبوط — مسارات الإدارة (تغيير الخطط) سترفض كل الطلبات حتى يُضبط.")

# ── تشفير مفاتيح API لمتاجر العملاء الخارجية (WooCommerce/Shopify) ─────
# مفتاح مستقل تماماً عن JWT_SECRET — لا يُستعمل إلا لتشفير/فك تشفير
# بيانات الاعتماد الحساسة قبل تخزينها بقاعدة البيانات، حتى لو سُرّبت القاعدة تبقى غير قابلة للقراءة.
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "").strip()
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    logging.warning("⚠️ ENCRYPTION_KEY غير مضبوط — تم توليد مفتاح مؤقت (سيُفقد عند إعادة التشغيل، "
                     "وستنقطع كل الاتصالات الخارجية المحفوظة). اضبط ENCRYPTION_KEY ثابت فالإنتاج فوراً.")
try:
    _fernet = Fernet(ENCRYPTION_KEY.encode())
except Exception as e:
    logging.error(f"ENCRYPTION_KEY غير صالح: {e} — تم توليد مفتاح بديل مؤقت")
    _fernet = Fernet(Fernet.generate_key())

def _encrypt_secret(text):
    return _fernet.encrypt(str(text).encode()).decode()

def _decrypt_secret(token):
    try:
        return _fernet.decrypt(str(token).encode()).decode()
    except (InvalidToken, Exception):
        return None

def issue_token(uid, username, role="owner", perms=None, member_username="", member_name=""):
    """يولّد JWT لصاحب الحساب (owner) أو لعضو فريق (member).
    uid/username دائماً يشيران لصاحب المتجر (owner) حتى بالنسبة لعضو الفريق،
    لأن كل بيانات المتجر مخزّنة تحت uid الخاص بصاحب الحساب — الصلاحيات (perms)
    هي اللي تتحكم بما يقدر العضو يوصله فعلياً عبر require_perm."""
    payload = {
        "uid": str(uid), "username": str(username), "role": role,
        "iat": int(time.time()), "exp": int(time.time()) + JWT_EXPIRY_HOURS * 3600,
    }
    if role == "member":
        payload["perms"]           = perms or {}
        payload["memberUsername"]  = member_username
        payload["memberName"]      = member_name or member_username
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        return None

def _extract_bearer(req):
    h = req.headers.get("Authorization", "")
    return h.split(" ", 1)[1].strip() if h.lower().startswith("bearer ") else ""

def require_auth(f):
    """يفرض تسجيل الدخول، ويحقن request.auth_uid / request.auth_username من الـ JWT فقط
    (لا يُعتمد أبداً على userId المرسل من العميل لتفادي انتحال حسابات أخرى).
    كما يحقن معلومات الدور (owner/member) وصلاحيات عضو الفريق إن وُجدت،
    ليستعملها require_perm بعد ذلك فتحديد الوصول لكل مسار."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _extract_bearer(request)
        payload = decode_token(token) if token else None
        if not payload or not payload.get("uid"):
            return err_json("Unauthorized — يرجى تسجيل الدخول من جديد", 401)
        request.auth_uid            = payload["uid"]
        request.auth_username       = payload.get("username", "")
        request.auth_role           = payload.get("role", "owner")
        request.auth_perms          = payload.get("perms", {}) or {}
        request.auth_member_username = payload.get("memberUsername", "")
        request.auth_member_name    = payload.get("memberName", "")
        return f(*args, **kwargs)
    return wrapper

def require_perm(perm):
    """يُستعمل بعد require_auth مباشرة لتقييد مسار مُعيّن بصلاحية محددة.
    صاحب الحساب (owner) يمر دائماً بلا قيود؛ عضو الفريق (member) يمر فقط
    إذا كانت الصلاحية المطلوبة مفعّلة له من طرف صاحب الحساب."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if getattr(request, "auth_role", "owner") != "member":
                return f(*args, **kwargs)
            if not (getattr(request, "auth_perms", {}) or {}).get(perm):
                return err_json("ليس لديك صلاحية الوصول لهذا القسم", 403)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def require_admin(f):
    """يحمي مسارات حساسة جداً (تغيير الخطط مثلاً) بمفتاح إدارة منفصل عن جلسات المستخدمين."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key", "").strip()
        if not ADMIN_API_KEY or key != ADMIN_API_KEY:
            return err_json("Forbidden", 403)
        return f(*args, **kwargs)
    return wrapper

def require_owner(f):
    """يحمي مسارات خاصة بصاحب الحساب فقط (لا تُفتح لأعضاء الفريق مهما كانت صلاحياتهم) —
    مثل إدارة الفريق نفسه، ربط فيسبوك/إنستغرام، وتفاصيل الحساب."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if getattr(request, "auth_role", "owner") != "owner":
            return err_json("هذه الميزة متاحة فقط لصاحب الحساب", 403)
        return f(*args, **kwargs)
    return wrapper

# ── Auth (Passwords) ──────────────────────────────────────
def _is_bcrypt_hash(pw):
    return isinstance(pw, str) and pw.startswith(("$2a$", "$2b$", "$2y$"))

def _hash_password(pw):
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _verify_password(pw, stored):
    if not stored: return False
    if _is_bcrypt_hash(stored):
        try:
            return bcrypt.checkpw(pw.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False
    # توافق مرحلي مع كلمات السر القديمة غير المُجزّأة (سيتم ترقيتها تلقائياً بعد أول دخول ناجح)
    return pw == stored

last_msg_time: dict   = {}
_rate_limit_lock      = threading.Lock()
_settings_cache: dict = {}
_settings_cache_lock  = threading.Lock()
_CACHE_TTL            = 120

# منع تكرار تسجيل نفس الطلب من البوت عدة مرات لنفس المحادثة
# (كان Gemini يعيد إرفاق بيانات JSON في كل رد بعد جمع المعلومات، مما يُنشئ طلباً مكرراً كل مرة)
_recent_bot_orders: dict   = {}
_recent_bot_orders_lock    = threading.Lock()
_DUPLICATE_ORDER_WINDOW    = 1800  # 30 دقيقة

def _is_duplicate_bot_order(sender_id, phone, product):
    key = f"{sender_id}"
    now = time.time()
    with _recent_bot_orders_lock:
        rec = _recent_bot_orders.get(key)
        if rec and rec.get("phone") == phone and rec.get("product") == product \
                and (now - rec.get("ts", 0)) < _DUPLICATE_ORDER_WINDOW:
            return True
    return False

def _mark_bot_order(sender_id, phone, product):
    with _recent_bot_orders_lock:
        _recent_bot_orders[sender_id] = {"phone": phone, "product": product, "ts": time.time()}

_SELF_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip()

def _keepalive_loop():
    sleep(60)
    while True:
        try:
            requests.get(f"{_SELF_URL or 'http://localhost:10000'}/health", timeout=10)
            logging.info("💓 Keepalive ping sent")
        except Exception as e:
            logging.warning(f"Keepalive failed: {e}")
        sleep(600)

threading.Thread(target=_keepalive_loop, daemon=True).start()

def _cleanup_rate_limit():
    while True:
        sleep(3600)
        cutoff = time.time() - 3600
        with _rate_limit_lock:
            to_del = [k for k, v in last_msg_time.items() if v < cutoff]
            for k in to_del:
                del last_msg_time[k]
        with _recent_bot_orders_lock:
            to_del2 = [k for k, v in _recent_bot_orders.items() if v.get("ts", 0) < cutoff]
            for k in to_del2:
                del _recent_bot_orders[k]

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

def _fb_get(path):
    try:
        return _firebase_ref(path).get()
    except Exception as e:
        logging.error(f"_fb_get({path}): {e}"); return None

def _fb_put(path, data):
    try:
        _firebase_ref(path).set(data)
        return True
    except Exception as e:
        logging.error(f"_fb_put({path}): {e}"); return False

def _fb_patch(path, data):
    try:
        _firebase_ref(path).update(data)
        return True
    except Exception as e:
        logging.error(f"_fb_patch({path}): {e}"); return False

def _fb_delete(path):
    try:
        _firebase_ref(path).delete()
        return True
    except Exception as e:
        logging.error(f"_fb_delete({path}): {e}"); return False

def _fb_push(path, data):
    try:
        new_ref = _firebase_ref(path).push(data)
        return new_ref.key
    except Exception as e:
        logging.error(f"_fb_push({path}): {e}"); return None

def _fb_list(path):
    data = _fb_get(path)
    if not data or not isinstance(data, dict): return []
    return list(reversed(list(data.values())))

def _firebase_ref(path):
    for attempt in range(3):
        try:
            return db.reference(path)
        except Exception as e:
            logging.warning(f"Firebase ref attempt {attempt+1}: {e}")
            if attempt < 2: sleep(1)
    raise ConnectionError(f"Firebase unreachable: {path}")

def ok_json(data):
    return jsonify({"status": "ok", "data": data})

def err_json(msg, code=400):
    return jsonify({"status": "error", "message": msg}), code

def is_rate_limited(user_id, platform="fb"):
    key = f"{platform}:{user_id}"
    now = time.time()
    with _rate_limit_lock:
        if key in last_msg_time and now - last_msg_time[key] < 2:
            return True
        last_msg_time[key] = now
    return False

# ── Plans ─────────────────────────────────────────────────
PLANS = {
    "free":       {"bot": False, "store": False, "dashboard": True, "orders": True, "integrations": False, "team": False, "label": "Free"},
    "starter":    {"bot": False, "store": True,  "dashboard": True, "orders": True, "integrations": False, "team": True,  "label": "Starter"},
    "pro":        {"bot": True,  "store": True,  "dashboard": True, "orders": True, "integrations": True,  "team": True,  "label": "Pro"},
    "enterprise": {"bot": True,  "store": True,  "dashboard": True, "orders": True, "integrations": True,  "team": True,  "label": "Enterprise"},
    # full = الاسم القديم (متوافق رجعياً مع حسابات قديمة)، lifetime = نفس الصلاحيات بالاسم الجديد للبيع
    "full":       {"bot": True,  "store": True,  "dashboard": True, "orders": True, "integrations": True,  "team": True,  "label": "Full",
                    "orderCap": 300, "botMsgCap": 3000},
    "lifetime":   {"bot": True,  "store": True,  "dashboard": True, "orders": True, "integrations": True,  "team": True,  "label": "Lifetime",
                    "orderCap": 300, "botMsgCap": 3000},
}

# مفتاح تفعيل البوت العام — True الآن بما أن ميتا وافقت وأصبح البوت جاهزاً فعلياً على إنستغرام.
# وقت يكون True، البوت يبان "متاح" بالداشبورد لكل خطة عندها bot:True بـ PLANS فوق.
# يمكن تعطيله مؤقتاً بضبط BOT_LAUNCHED=false كمتغير بيئة بلا حاجة لإعادة نشر الكود.
BOT_LAUNCHED = os.environ.get("BOT_LAUNCHED", "true").strip().lower() == "true"

# ── فريق العمل (Team Members) ──────────────────────────────
# كل صاحب حساب (owner) يقدر يضيف حتى MAX_TEAM_MEMBERS من أعضاء الفريق، كل واحد
# عندو اسم دخول وكلمة سر خاصة بيه، لكن يشتغل على نفس بيانات المتجر (data/{ownerUid}/...)
# حسب الصلاحيات (permissions) اللي يحددها صاحب الحساب فقط.
MAX_TEAM_MEMBERS = 6
TEAM_PERM_KEYS = ["orders", "products", "customers", "cities", "store", "bot", "messages", "integrations"]

def _clean_perms(raw):
    raw = raw or {}
    return {k: bool(raw.get(k)) for k in TEAM_PERM_KEYS}

def _count_team_members(owner_uid):
    try:
        raw = _fb_get(f"data/{owner_uid}/teamMembers") or {}
        return len([1 for v in raw.values() if isinstance(v, dict)])
    except Exception:
        return 0

# ── تتبع الاستهلاك الشهري (لحماية سقوف Lifetime/Full) ─────
def _usage_month_key():
    return time.strftime("%Y-%m")

def _get_usage(uid, field):
    val = _fb_get(f"data/{uid}/usage/{_usage_month_key()}/{field}") or 0
    try: return int(val)
    except Exception: return 0

def _increment_usage(uid, field):
    new_val = _get_usage(uid, field) + 1
    _fb_put(f"data/{uid}/usage/{_usage_month_key()}/{field}", new_val)
    return new_val

def _plan_cap(uid, cap_field):
    """يرجع رقم السقف لهذا المستخدم لهذا النوع (None = بلا سقف)."""
    plan = get_user_plan(uid)
    return PLANS.get(plan, {}).get(cap_field)

def _under_cap(uid, usage_field, cap_field):
    cap = _plan_cap(uid, cap_field)
    if not cap: return True  # بلا سقف لهذي الخطة
    return _get_usage(uid, usage_field) < cap

LIFETIME_MAX_SLOTS = 50

def _get_user_record(uid):
    """يرجع سجل المستخدم كامل (خطة، مصدر...) من عقدة users — استدعاء واحد يُستعمل فعدة أماكن."""
    try:
        users = _fb_get("users") or {}
        for _, u in users.items():
            if isinstance(u, dict) and str(u.get("User_ID", "")) == str(uid):
                return u
    except Exception:
        pass
    return {}

def get_user_plan(uid):
    return str(_get_user_record(uid).get("plan", "starter")).lower()

def _count_lifetime_accounts():
    """عدد حسابات Lifetime/Full الحالية (الاسمين يحسبان لنفس السقف 50)."""
    try:
        users = _fb_get("users") or {}
        return sum(1 for u in users.values() if isinstance(u, dict) and u.get("plan") in ("lifetime", "full"))
    except Exception:
        return 0

# ── Frontend ──────────────────────────────────────────────
@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory("static", "index.html")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "OrderFlow", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}), 200

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
      showMsg("createMsg","✅ تم إنشاء الحساب بنجاح ("+plan+" / "+source+")","ok");
      document.getElementById("createResult").innerHTML =
        '<div class="result-box">'+
          '<div>👤 اسم المستخدم: <code>'+username+'</code></div>'+
          '<div>🔑 كلمة السر: <code>'+password+'</code></div>'+
          '<div>🔗 رابط المتجر: <code id="lk">'+data.data.storeLink+'</code></div>'+
          '<button class="copy-btn" onclick="copyText(\\''+username+' / '+password+'\\')">نسخ بيانات الدخول</button>'+
          '<button class="copy-btn" onclick="copyText(\\''+data.data.storeLink+'\\')">نسخ رابط المتجر</button>'+
        '</div>';
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
    if(data.status!=="ok"){ box.innerHTML = "❌ "+data.message; return; }

    var lifetimeUsed = data.data.filter(function(c){ return c.plan==="lifetime"||c.plan==="full"; }).length;
    var lifetimeLeftEl = document.getElementById("lifetimeSlotsDisplay");
    if(lifetimeLeftEl) lifetimeLeftEl.textContent = Math.max(0, 50-lifetimeUsed);

    if(!data.data.length){ box.innerHTML = "لا يوجد عملاء بعد"; return; }
    box.innerHTML = '<table><thead><tr><th>المستخدم</th><th>ID</th><th>المصدر</th><th>الخطة</th><th>تغيير الخطة</th></tr></thead><tbody>'+
      data.data.map(function(c){
        var srcBadge = c.source==="fiverr" ? '<span class="badge b-pro">Fiverr</span>' : '<span class="badge b-starter">محلي</span>';
        return '<tr><td>'+c.username+'</td><td style="font-size:10px;color:#8899bb">'+c.userId+'</td>'+
          '<td>'+srcBadge+'</td>'+
          '<td><span class="badge b-'+c.plan+'">'+c.plan.toUpperCase()+'</span></td>'+
          '<td><select onchange="changePlan(\\''+c.userId+'\\',\\''+c.username+'\\',this.value)">'+
            ["free","starter","pro","enterprise","full","lifetime"].map(function(p){
              return '<option value="'+p+'"'+(p===c.plan?" selected":"")+'>'+p+'</option>';
            }).join("")+
          '</select></td></tr>';
      }).join("")+
      '</tbody></table>';
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

@app.route("/privacy", methods=["GET"])
def privacy_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>OrderFlow AI — Privacy Policy & Terms</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Arial,sans-serif;background:#0d1b2e;color:#e8edf5;line-height:1.8}
.header{background:#0a1628;border-bottom:1px solid rgba(255,255,255,.08);padding:20px 0;text-align:center}
.header h1{font-size:28px;font-weight:800;color:#2563eb}
.header p{font-size:13px;color:#8899bb;margin-top:4px}
.container{max-width:860px;margin:0 auto;padding:40px 20px}
.section{background:#111f35;border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:28px;margin-bottom:24px}
h2{font-size:18px;font-weight:700;color:#60a5fa;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.07)}
h3{font-size:14px;font-weight:700;color:#e8edf5;margin:16px 0 8px}
p,li{font-size:13px;color:#94a3b8;margin-bottom:8px}
ul{padding-left:20px}
li{margin-bottom:6px}
.badge{display:inline-block;background:#1e3a5f;color:#60a5fa;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;margin-bottom:16px}
.contact-box{background:#0f2a4a;border:1px solid #1e3a5f;border-radius:10px;padding:16px;margin-top:12px}
.contact-box a{color:#60a5fa;text-decoration:none;font-weight:700}
.contact-box a:hover{text-decoration:underline}
.highlight{color:#10b981;font-weight:700}
.footer{text-align:center;padding:30px;color:#475569;font-size:12px;border-top:1px solid rgba(255,255,255,.07);margin-top:20px}
.tag{display:inline-block;background:rgba(37,99,235,.15);color:#60a5fa;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.product-box{background:#0a1628;border-radius:10px;padding:20px;margin-top:12px}
.product-box .feature{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.product-box .feature .icon{font-size:18px;flex-shrink:0}
.product-box .feature p{margin:0;font-size:13px;color:#94a3b8}
.product-box .feature strong{color:#e8edf5}
</style>
</head>
<body>

<div class="header">
  <h1>📦 OrderFlow AI</h1>
  <p>Complete E-Commerce Automation Platform — orderconfidence.com</p>
</div>

<div class="container">

  <div class="section">
    <span class="badge">🚀 About Our Platform</span>
    <h2>What is OrderFlow AI?</h2>
    <p>OrderFlow AI is a complete SaaS (Software as a Service) platform designed specifically for e-commerce businesses in Algeria and the Arab world. We automate the entire sales management workflow, from order intake to delivery tracking.</p>
    <div class="product-box">
      <div class="feature"><div class="icon">📦</div><div><p><strong>Order Management</strong> — Track all orders with real-time status updates (Pending, Confirmed, Delivered, Refused)</p></div></div>
      <div class="feature"><div class="icon">🤖</div><div><p><strong>AI Bot (WhatsApp & Facebook)</strong> — Gemini-powered chatbot that automatically responds to customers and creates orders from conversations</p></div></div>
      <div class="feature"><div class="icon">🛒</div><div><p><strong>Online Store</strong> — Each merchant gets a public catalog page with cart functionality for customers</p></div></div>
      <div class="feature"><div class="icon">📊</div><div><p><strong>Dashboard & Analytics</strong> — Real-time profits, confirmation rates, top products, and low stock alerts</p></div></div>
      <div class="feature"><div class="icon">🏙️</div><div><p><strong>City & Shipping Management</strong> — Configure shipping costs per city with automatic profit calculation</p></div></div>
    </div>
    <p style="margin-top:16px">Our platform serves Algerian e-commerce sellers who use Facebook, Instagram, and WhatsApp to sell products. We help them organize orders, automate responses, and grow their business.</p>
    <div style="margin-top:12px">
      <span class="tag">E-Commerce</span>
      <span class="tag">Order Management</span>
      <span class="tag">AI Chatbot</span>
      <span class="tag">WhatsApp Business</span>
      <span class="tag">Facebook Messenger</span>
      <span class="tag">Instagram DM</span>
    </div>
  </div>

  <div class="section">
    <span class="badge">🛡️ Privacy Policy</span>
    <h2>Privacy Policy</h2>
    <p><strong>Effective Date:</strong> June 17, 2026 &nbsp;|&nbsp; <strong>Last Updated:</strong> June 17, 2026</p>

    <h3>1. Information We Collect</h3>
    <p>When merchants connect their Facebook or Instagram pages to OrderFlow AI, we collect:</p>
    <ul>
      <li>Facebook Page ID and access tokens (to receive and send messages)</li>
      <li>Instagram Business Account ID and access tokens</li>
      <li>Customer messages sent to connected pages (for AI bot processing only)</li>
      <li>Order information provided by customers during conversations (name, phone, city, product)</li>
    </ul>

    <h3>2. How We Use Your Data</h3>
    <ul>
      <li><span class="highlight">Order Processing:</span> Customer messages are processed by our AI to extract order details and create orders in the merchant's dashboard</li>
      <li><span class="highlight">Automated Responses:</span> Our AI bot responds to customers on behalf of merchants</li>
      <li><span class="highlight">Analytics:</span> We calculate profits, confirmation rates, and stock levels for merchants</li>
      <li><span class="highlight">We do NOT sell, share, or transfer</span> any data to third parties</li>
    </ul>

    <h3>3. Data Storage</h3>
    <ul>
      <li>All data is stored securely in <strong>Google Firebase</strong> (Europe West region)</li>
      <li>Facebook access tokens are stored encrypted and used solely to communicate with Meta APIs</li>
      <li>Chat histories are stored per-user and accessible only to the merchant</li>
      <li>Merchants can delete their data at any time by contacting us</li>
    </ul>

    <h3>4. Meta Platform Data</h3>
    <ul>
      <li>We access Facebook and Instagram APIs only with explicit merchant permission via OAuth</li>
      <li>We only request permissions necessary for order automation: <code>pages_messaging</code>, <code>instagram_manage_messages</code>, <code>pages_read_engagement</code></li>
      <li>We do not access personal profiles, friend lists, or any data beyond page messages</li>
      <li>Merchants can disconnect their Facebook/Instagram at any time from the Settings page</li>
    </ul>

    <h3>5. Data Retention</h3>
    <p>We retain merchant data for as long as the account is active. Upon account deletion request, all associated data is permanently removed within 30 days.</p>

    <h3>6. Security</h3>
    <p>We implement industry-standard security measures including HTTPS encryption, Firebase security rules, and token-based authentication to protect your data.</p>
  </div>

  <div class="section">
    <span class="badge">📋 Terms of Service</span>
    <h2>Terms of Service</h2>
    <p><strong>Effective Date:</strong> June 17, 2026</p>

    <h3>1. Acceptance</h3>
    <p>By using OrderFlow AI, you agree to these terms. If you do not agree, please discontinue use of our platform.</p>

    <h3>2. Permitted Use</h3>
    <ul>
      <li>OrderFlow AI is intended for legitimate e-commerce businesses</li>
      <li>Users must comply with Meta's Platform Policies when using the bot features</li>
      <li>Users must not use the platform to send spam, misleading messages, or violate customer privacy</li>
      <li>Each merchant is responsible for the content of automated messages sent through their account</li>
    </ul>

    <h3>3. Subscription Plans</h3>
    <ul>
      <li><strong>Free:</strong> Basic order management and dashboard — 0 DZD</li>
      <li><strong>Starter:</strong> Includes online store — one-time payment</li>
      <li><strong>Pro:</strong> Includes AI Bot (WhatsApp + Facebook) — monthly subscription</li>
      <li><strong>Full:</strong> All features, lifetime access — one-time payment</li>
    </ul>
    <p>Plan upgrades are managed by the platform administrator. Contact us to change your plan.</p>

    <h3>4. Limitation of Liability</h3>
    <p>OrderFlow AI provides tools for order management and automation. We are not responsible for business losses, customer disputes, or issues arising from how merchants use our platform.</p>

    <h3>5. Account Termination</h3>
    <p>We reserve the right to suspend or terminate accounts that violate these terms or Meta's policies.</p>

    <h3>6. Changes to Terms</h3>
    <p>We may update these terms periodically. Continued use of the platform constitutes acceptance of updated terms.</p>
  </div>

  <div class="section">
    <span class="badge">🗑️ Data Deletion</span>
    <h2>Data Deletion Request</h2>
    <p>In compliance with Meta's Platform Policy, users can request deletion of all their data from our system.</p>
    <p>To request data deletion:</p>
    <ul>
      <li>Send an email to <strong style="color:#60a5fa">orderflowai927@gmail.com</strong> with the subject "Data Deletion Request"</li>
      <li>Include your username or User ID</li>
      <li>We will confirm deletion within <strong>30 days</strong></li>
    </ul>
    <p>You can also disconnect Facebook/Instagram at any time from <strong>Settings → Facebook/Meta → Déconnecter</strong> in the app.</p>
  </div>

  <div class="section">
    <span class="badge">📞 Contact Us</span>
    <h2>Contact Information</h2>
    <p>For questions about privacy, data, or our platform:</p>
    <div class="contact-box">
      <p>📧 <strong>Email:</strong> <a href="mailto:orderflowai927@gmail.com">orderflowai927@gmail.com</a></p>
      <p>🌐 <strong>Website:</strong> <a href="https://orderconfidence.com">https://orderconfidence.com</a></p>
      <p>📦 <strong>Platform:</strong> OrderFlow AI — E-Commerce Management SaaS</p>
      <p>📍 <strong>Location:</strong> Algeria</p>
    </div>
    <p style="margin-top:16px;font-size:12px;color:#475569">
      We typically respond to all inquiries within 48 hours.
    </p>
  </div>

</div>

<div class="footer">
  © 2026 OrderFlow AI — orderconfidence.com &nbsp;|&nbsp;
  <a href="mailto:orderflowai927@gmail.com" style="color:#60a5fa">orderflowai927@gmail.com</a>
</div>

</body>
</html>""", 200

@app.route("/terms", methods=["GET"])
def terms_redirect():
    from flask import redirect
    return redirect("/privacy")

# ── Auth ──────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(silent=True) or {}
    user = str(body.get("username") or "").strip()
    pwd  = str(body.get("password") or "").strip()
    if not user or not pwd:
        return err_json("Missing credentials")

    # 1) نحاول أولاً كصاحب حساب رئيسي (owner) — عقدة users/
    users = _fb_get("users") or {}
    if isinstance(users, dict):
        for key, udata in users.items():
            if not isinstance(udata, dict): continue
            if str(udata.get("Username") or "").lower() != user.lower():
                continue
            stored_pw = str(udata.get("Password") or "")
            if not _verify_password(pwd, stored_pw):
                return err_json("Invalid credentials", 401)
            # ترقية شفافة من كلمة سر نصية قديمة إلى bcrypt بعد أول دخول ناجح
            if not _is_bcrypt_hash(stored_pw):
                _fb_patch(f"users/{key}", {"Password": _hash_password(pwd)})
            token = issue_token(udata.get("User_ID", ""), udata.get("Username", user), role="owner")
            safe  = {k: v for k, v in udata.items() if k != "Password"}
            safe["token"] = token
            safe["role"]  = "owner"
            return ok_json(safe)

    # 2) لم يُوجد كصاحب حساب — نحاول كعضو فريق (team member) — عقدة team_users/
    member = _fb_get(f"team_users/{user}")
    member_key = user
    if not member or not isinstance(member, dict):
        all_members = _fb_get("team_users") or {}
        member = None
        if isinstance(all_members, dict):
            for k, m in all_members.items():
                if isinstance(m, dict) and str(m.get("Username") or "").lower() == user.lower():
                    member = m; member_key = k; break
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
    if len(password) < 4:
        return err_json("كلمة السر قصيرة جداً (4 أحرف على الأقل)")
    if not planHas_server(uid, "team"):
        return err_json("ميزة الفريق غير متاحة لخطتك الحالية", 403)
    if _count_team_members(uid) >= MAX_TEAM_MEMBERS:
        return err_json(f"وصلت للحد الأقصى ({MAX_TEAM_MEMBERS}) من أعضاء الفريق", 409)
    # منع تعارض اسم المستخدم مع حساب رئيسي أو عضو آخر بأي متجر
    if _fb_get(f"users/{username}") or _fb_get(f"team_users/{username}"):
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
        if len(newpass) < 4: return err_json("كلمة السر قصيرة جداً (4 أحرف على الأقل)")
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
    return ok_json(True)

def planHas_server(uid, feature):
    """يتحقق سيرفرياً أن خطة صاحب هذا الـ uid تدعم ميزة معينة — يُستعمل لمنع تحايل
    عضو فريق أو طلب مباشر على قيود الخطة (مثلاً تفعيل ميزة الفريق بدون خطة تدعمها)."""
    plan = get_user_plan(uid)
    return bool(PLANS.get(plan, {}).get(feature, False))

# ── Orders ────────────────────────────────────────────────
@app.route("/api/getOrders", methods=["GET"])
@require_auth
@require_perm("orders")
def api_get_orders():
    uid = request.auth_uid
    return ok_json(_fb_list(f"data/{uid}/orders"))

def _ship_values(c_data, delivery_type):
    """يرجع (سعر الزبون، تكلفة التاجر) للتوصيل حسب النوع — منزل أو مكتب استلام."""
    is_desk = delivery_type == "desk"
    ship_cust = float(c_data.get("deskCust", 0)) if is_desk else float(c_data.get("custShip", 0))
    ship_cost = float(c_data.get("deskCost", 0)) if is_desk else float(c_data.get("costShip", 0))
    return ship_cust, ship_cost

def _calc_order_profit(p_data, c_data, qty, delivery_type, status, existing_profit=0.0):
    """نفس منطق حساب الربح بمكان واحد — يُستعمل عند تأكيد الطلب وعند تعديل نوع التوصيل لاحقاً."""
    ship_cust, ship_cost = _ship_values(c_data, delivery_type)
    if status in ("Confirmed", "Delivered"):
        return ((float(p_data.get("sell", 0)) - float(p_data.get("cost", 0))) * int(qty)) + (ship_cust - ship_cost)
    elif status == "Refused":
        return -float(c_data.get("returnFee", 0))
    return existing_profit

@app.route("/api/addOrder", methods=["POST"])
def api_add_order():
    body = request.get_json(silent=True) or {}
    uid  = str(body.get("userId") or "").strip()
    d    = body.get("data") or {}
    if not uid or not d: return err_json("Missing fields")
    if not _under_cap(uid, "orderCount", "orderCap"):
        return err_json("تم الوصول للحد الشهري من الطلبات لهذه الخطة — يرجى التواصل لترقية الخطة", 429)
    order_id       = f"ORD-{int(time.time() * 1000)}"
    d["id"]        = order_id
    d["date"]      = time.strftime("%Y-%m-%d %H:%M")
    d["status"]    = d.get("status") or "Pending"
    d["profit"]    = 0
    d["source"]    = d.get("source") or "manual"
    d["deliveryType"] = d.get("deliveryType") if d.get("deliveryType") in ("home","desk") else "home"
    d["date_sent"] = ""
    d["date_delivered"] = ""
    p_data = _fb_get(f"data/{uid}/products/{d.get('product')}")
    c_data = _fb_get(f"data/{uid}/cities/{d.get('city')}")
    if p_data and c_data and not d.get("total"):
        ship_cust, _ = _ship_values(c_data, d["deliveryType"])
        d["total"] = (float(p_data.get("sell", 0)) * int(d.get("qty", 1))) + ship_cust
    _fb_put(f"data/{uid}/orders/{order_id}", d)
    _increment_usage(uid, "orderCount")
    return ok_json({"orderId": order_id})

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
            if status == "Confirmed":
                _update_product_stock(uid, order.get("product", ""))
    order["profit"] = profit
    _fb_put(f"data/{uid}/orders/{oid}", order)
    return ok_json(True)

@app.route("/api/updateOrderDelivery", methods=["POST"])
@require_auth
@require_perm("orders")
def api_update_order_delivery():
    """تعديل نوع التوصيل لطلب موجود (مثلاً العميل تراجع عن الاستلام بالمنزل وفضّل مكتب الاستلام)،
    مع إعادة حساب الإجمالي والربح تلقائياً بنفس منطق الحساب الموحّد — بلا كسر أي رقم سابق."""
    body  = request.get_json(silent=True) or {}
    uid   = request.auth_uid
    oid   = str(body.get("orderId") or "").strip()
    dtype = str(body.get("deliveryType") or "").strip()
    if not oid or dtype not in ("home", "desk"):
        return err_json("Missing or invalid fields")
    order = _fb_get(f"data/{uid}/orders/{oid}")
    if not order: return err_json("Order not found", 404)
    order["deliveryType"] = dtype
    p_data = _fb_get(f"data/{uid}/products/{order.get('product')}")
    c_data = _fb_get(f"data/{uid}/cities/{order.get('city')}")
    if p_data and c_data:
        ship_cust, _ = _ship_values(c_data, dtype)
        order["total"]  = (float(p_data.get("sell", 0)) * int(order.get("qty", 1))) + ship_cust
        order["profit"] = _calc_order_profit(p_data, c_data, order.get("qty", 1), dtype, order.get("status",""), order.get("profit", 0))
    _fb_put(f"data/{uid}/orders/{oid}", order)
    return ok_json(True)

def _update_product_stock(uid, product_name):
    try:
        p_data = _fb_get(f"data/{uid}/products/{product_name}")
        if not p_data: return
        orders = _fb_get(f"data/{uid}/orders") or {}
        sold   = sum(int(o.get("qty", 0)) for o in orders.values()
                     if isinstance(o, dict) and o.get("product") == product_name
                     and o.get("status") in ("Confirmed", "Delivered"))
        init      = int(p_data.get("init", 0))
        available = max(0, init - sold)
        stat      = ("Out of Stock" if available <= 0
                     else "Low Stock" if available <= LOW_STOCK_THRESHOLD else "In Stock")
        _fb_patch(f"data/{uid}/products/{product_name}", {"sold": sold, "available": available, "stat": stat})
    except Exception as e:
        logging.error(f"_update_product_stock: {e}")

# ── Products ──────────────────────────────────────────────
@app.route("/api/getProducts", methods=["GET"])
@require_auth
@require_perm("products")
def api_get_products():
    uid = request.auth_uid
    return ok_json(_fb_list(f"data/{uid}/products"))

@app.route("/api/getStoreProducts", methods=["GET"])
def api_get_store_products():
    uid = request.args.get("userId", "").strip()
    if not uid: return err_json("Missing userId")
    products_raw = _fb_get(f"data/{uid}/products") or {}
    orders_raw   = _fb_get(f"data/{uid}/orders")   or {}
    ratings_raw  = _fb_get(f"data/{uid}/ratings")  or {}
    sales = {}
    for o in orders_raw.values():
        if isinstance(o, dict) and o.get("status") in ("Confirmed", "Delivered"):
            name = o.get("product", "")
            sales[name] = sales.get(name, 0) + int(o.get("qty", 0))
    result = []
    for p in products_raw.values():
        if not isinstance(p, dict) or not p.get("name"): continue
        init      = int(p.get("init", 0))
        sold      = sales.get(p["name"], 0)
        available = max(0, init - sold)
        stat      = ("Out of Stock" if available <= 0
                     else "Low Stock" if available <= LOW_STOCK_THRESHOLD else "In Stock")
        images = p.get("images") or ([p["image"]] if p.get("image") else [])
        prod_ratings = ratings_raw.get(p["name"]) if isinstance(ratings_raw, dict) else None
        avg_rating = rating_count = 0
        if isinstance(prod_ratings, dict) and prod_ratings:
            vals = [float(r.get("rating", 0)) for r in prod_ratings.values() if isinstance(r, dict)]
            if vals:
                rating_count = len(vals)
                avg_rating   = round(sum(vals) / rating_count, 1)
        result.append({"name": p.get("name",""), "category": p.get("category",""),
                        "size": p.get("size",""), "colors": p.get("colors",""),
                        "sell": float(p.get("sell",0)), "available": available, "stat": stat, "sold": sold,
                        "description": p.get("description",""), "image": p.get("image",""), "images": images,
                        "visible": p.get("visible","yes"), "created_at": p.get("created_at", 0),
                        "avgRating": avg_rating, "ratingCount": rating_count})
    result.sort(key=lambda x: {"In Stock":0,"Low Stock":1,"Out of Stock":2}.get(x["stat"],0))
    return ok_json(result)

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
    return ok_json(True)

@app.route("/api/trackOrder", methods=["GET"])
def api_track_order():
    """تتبع عام للعميل عبر رقم الهاتف — لا يكشف الربح الداخلي (profit) أو بيانات عملاء آخرين."""
    uid   = request.args.get("userId", "").strip()
    phone = re.sub(r"\D", "", request.args.get("phone", ""))
    if not uid or not phone: return err_json("Missing userId or phone")
    orders_raw = _fb_get(f"data/{uid}/orders") or {}
    result = []
    for o in orders_raw.values():
        if not isinstance(o, dict): continue
        if re.sub(r"\D", "", str(o.get("phone", ""))) == phone:
            result.append({"id": o.get("id",""), "product": o.get("product",""),
                            "qty": o.get("qty",1), "status": o.get("status",""),
                            "date": o.get("date",""), "total": o.get("total",0),
                            "city": o.get("city",""), "rated": bool(o.get("rated", False))})
    result.sort(key=lambda x: x.get("date",""), reverse=True)
    return ok_json(result)

@app.route("/api/submitRating", methods=["POST"])
def api_submit_rating():
    """تقييم حقيقي مرتبط بطلب مُسلَّم فعلاً — يمنع التقييمات المزوّرة بدون عملية شراء حقيقية."""
    body    = request.get_json(silent=True) or {}
    uid     = str(body.get("userId") or "").strip()
    order_id= str(body.get("orderId") or "").strip()
    phone   = re.sub(r"\D", "", str(body.get("phone") or ""))
    comment = str(body.get("comment") or "").strip()[:500]
    try:
        rating = int(body.get("rating"))
    except Exception:
        return err_json("Invalid rating")
    if not uid or not order_id or not phone: return err_json("Missing fields")
    if rating < 1 or rating > 5: return err_json("Rating must be between 1 and 5")
    order = _fb_get(f"data/{uid}/orders/{order_id}")
    if not order: return err_json("Order not found", 404)
    if re.sub(r"\D", "", str(order.get("phone",""))) != phone:
        return err_json("Unauthorized", 403)
    if order.get("status") != "Delivered":
        return err_json("Order not yet delivered")
    if order.get("rated"):
        return err_json("Order already rated")
    product = order.get("product", "")
    if not product: return err_json("Invalid order")
    _fb_push(f"data/{uid}/ratings/{product}", {
        "rating": rating, "comment": comment, "date": time.strftime("%Y-%m-%d %H:%M"),
        "orderId": order_id,
    })
    _fb_patch(f"data/{uid}/orders/{order_id}", {"rated": True})
    return ok_json(True)

@app.route("/api/getProductRatings", methods=["GET"])
def api_get_product_ratings():
    uid     = request.args.get("userId", "").strip()
    product = request.args.get("product", "").strip()
    if not uid or not product: return err_json("Missing fields")
    raw = _fb_get(f"data/{uid}/ratings/{product}") or {}
    items = []
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, dict):
                items.append({"rating": v.get("rating", 0), "comment": v.get("comment", ""), "date": v.get("date", "")})
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return ok_json(items)

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

@app.route("/api/getStoreCities", methods=["GET"])
def api_get_store_cities():
    """نسخة عامة آمنة للمتجر — لا تكشف تكلفة التوصيل الداخلية أو رسوم الإرجاع."""
    uid = request.args.get("userId", "").strip()
    if not uid: return err_json("Missing userId")
    raw    = _fb_get(f"data/{uid}/cities") or {}
    cities = []
    for k, v in raw.items():
        if isinstance(v, dict):
            cities.append({
                "name": v.get("name", k),
                "custShip": float(v.get("custShip", 0)),       # توصيل للمنزل
                "deskCust": float(v.get("deskCust", 0)),        # توصيل لمكتب الاستلام
            })
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
    _fb_put(f"data/{uid}/cities/{name}", {
        "name": name,
        "costShip": float(d.get("costShip",0)), "custShip": float(d.get("custShip",0)),  # توصيل للمنزل (الأسماء القديمة، بلا تغيير)
        "deskCost": float(d.get("deskCost",0)), "deskCust": float(d.get("deskCust",0)),  # توصيل لمكتب الاستلام (جديد)
        "returnFee": float(d.get("returnFee",0)),
    })
    return ok_json(True)

# ── Customers ─────────────────────────────────────────────
@app.route("/api/getCustomers", methods=["GET"])
@require_auth
@require_perm("customers")
def api_get_customers():
    uid = request.auth_uid
    orders_raw = _fb_get(f"data/{uid}/orders") or {}
    cmap = {}
    for o in orders_raw.values():
        if not isinstance(o, dict): continue
        ph = re.sub(r"\D", "", str(o.get("phone") or ""))
        if not ph: continue
        if ph not in cmap:
            cmap[ph] = {"name": o.get("name",""), "phone": o.get("phone",""),
                        "city": o.get("city",""), "totalOrders": 0,
                        "stats": {"confirmed":0,"refused":0,"delivered":0}}
        cmap[ph]["totalOrders"] += 1
        st = o.get("status","")
        if st == "Confirmed": cmap[ph]["stats"]["confirmed"] += 1
        if st == "Refused":   cmap[ph]["stats"]["refused"]   += 1
        if st == "Delivered": cmap[ph]["stats"]["delivered"] += 1
    result = []
    for ph, c in cmap.items():
        ref = c["stats"]["refused"]
        con = c["stats"]["confirmed"] + c["stats"]["delivered"]
        rating = "Bad" if ref >= BAD_CUSTOMER_THRESHOLD else "Good" if con >= 3 and ref == 0 else "Neutral"
        result.append({**c, "type": rating})
    return ok_json(result)

# ── Dashboard ─────────────────────────────────────────────
@app.route("/api/getDashboard", methods=["GET"])
@require_auth
def api_get_dashboard():
    uid = request.auth_uid
    orders_raw   = _fb_get(f"data/{uid}/orders")   or {}
    products_raw = _fb_get(f"data/{uid}/products") or {}
    tot = conf = ref = delivered = 0
    profit = 0.0
    sales  = {}
    for o in orders_raw.values():
        if not isinstance(o, dict): continue
        tot += 1
        st = o.get("status","")
        if st in ("Confirmed","Delivered"):
            conf += 1
            profit += float(o.get("profit",0))
            prod = o.get("product","")
            sales[prod] = sales.get(prod,0) + int(o.get("qty",1))
            if st == "Delivered": delivered += 1
        elif st == "Refused":
            ref += 1
            profit += float(o.get("profit",0))
    top_products = sorted([{"name":k,"qty":v} for k,v in sales.items()],
                          key=lambda x: x["qty"], reverse=True)[:5]
    low_stock = []
    for p in products_raw.values():
        if not isinstance(p, dict): continue
        remaining = int(p.get("init",0)) - sales.get(p.get("name",""),0)
        if remaining <= LOW_STOCK_THRESHOLD:
            low_stock.append({"name":p.get("name",""),"rem":remaining,
                               "stat":"Out of Stock" if remaining<=0 else "Low Stock"})
    return ok_json({"totalOrders":tot,"confirmed":conf,"refused":ref,"delivered":delivered,
                    "totalProfit":round(profit,2),"confirmRate":round(conf/tot*100) if tot else 0,
                    "refuseRate":round(ref/tot*100) if tot else 0,
                    "topProducts":top_products,"lowStock":low_stock})

# ── Store Settings ────────────────────────────────────────
@app.route("/api/getStoreSettings", methods=["GET"])
def api_get_store_settings():
    uid = request.args.get("userId","").strip()
    if not uid: return err_json("Missing userId")
    return ok_json(_fb_get(f"data/{uid}/storeSettings") or {})

@app.route("/api/updateStoreSettings", methods=["POST"])
@require_auth
@require_perm("store")
def api_update_store_settings():
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    d    = body.get("data") or {}
    # تحديث جزئي: نحدّث فقط الحقول المُرسلة فعلاً، بلا مسح باقي الإعدادات
    # (كان الكود القديم يكتب القيم الافتراضية فوق أي حقل غير مُرسل، فيمسح اسم/شعار المتجر بالغلط)
    patch = {}
    for field, default in (("name","My Store"), ("tagline",""), ("logo","🛒"), ("logoImage",""), ("lang","AR"), ("currency","DZD")):
        if field in d:
            patch[field] = d[field]
    if patch:
        existing = _fb_get(f"data/{uid}/storeSettings")
        if existing:
            _fb_patch(f"data/{uid}/storeSettings", patch)
        else:
            for field, default in (("name","My Store"), ("tagline",""), ("logo","🛒"), ("logoImage",""), ("lang","AR"), ("currency","DZD")):
                patch.setdefault(field, default)
            _fb_put(f"data/{uid}/storeSettings", patch)
    return ok_json(True)

# ── WooCommerce Integration ───────────────────────────────
@app.route("/api/woo/connect", methods=["POST"])
@require_auth
@require_perm("integrations")
def api_woo_connect():
    """ربط متجر WooCommerce حقيقي — يتحقق من المفاتيح بطلب فعلي للمتجر قبل الحفظ، ويشفّرها قبل التخزين."""
    body = request.get_json(silent=True) or {}
    uid  = request.auth_uid
    store_url = str(body.get("storeUrl") or "").strip().rstrip("/")
    consumer_key    = str(body.get("consumerKey") or "").strip()
    consumer_secret = str(body.get("consumerSecret") or "").strip()
    if not store_url or not consumer_key or not consumer_secret:
        return err_json("جميع الحقول مطلوبة")
    if not store_url.startswith("https://"):
        return err_json("رابط المتجر يجب أن يبدأ بـ https:// لحماية بيانات متجرك")
    try:
        test = requests.get(f"{store_url}/wp-json/wc/v3/orders", params={"per_page": 1},
                             auth=(consumer_key, consumer_secret), timeout=15)
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
    """يجلب آخر الطلبات من WooCommerce ويستوردها لـ OrderFlow (بلا تكرار، يتفادى أي طلب مستورد من قبل)."""
    uid   = request.auth_uid
    integ = _fb_get(f"data/{uid}/integrations/woocommerce")
    if not integ or not integ.get("connected"):
        return err_json("المتجر غير مربوط — اربطه أولاً")
    store_url = integ.get("storeUrl", "")
    ck = _decrypt_secret(integ.get("consumerKeyEnc", ""))
    cs = _decrypt_secret(integ.get("consumerSecretEnc", ""))
    if not ck or not cs:
        return err_json("فشل قراءة بيانات الربط — أعد ربط المتجر من جديد")
    try:
        r = requests.get(f"{store_url}/wp-json/wc/v3/orders",
                          params={"per_page": 50, "orderby": "date", "order": "desc"},
                          auth=(ck, cs), timeout=20)
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

    existing_orders   = _fb_get(f"data/{uid}/orders") or {}
    existing_woo_ids  = {str(o.get("wooOrderId")) for o in existing_orders.values()
                          if isinstance(o, dict) and o.get("wooOrderId")}
    imported = 0
    for wo in woo_orders:
        if not _under_cap(uid, "orderCount", "orderCap"):
            logging.warning(f"⏭️ توقفت مزامنة WooCommerce — تجاوز سقف الطلبات الشهري | uid={uid}")
            break
        woo_id = str(wo.get("id", ""))
        if not woo_id or woo_id in existing_woo_ids: continue
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
        _fb_put(f"data/{uid}/orders/{order_id}", new_order)
        _increment_usage(uid, "orderCount")
        imported += 1
    _fb_patch(f"data/{uid}/integrations/woocommerce", {"lastSync": time.strftime("%Y-%m-%d %H:%M")})
    return ok_json({"imported": imported, "checked": len(woo_orders)})


@app.route("/api/uploadImage", methods=["POST"])
@require_auth
def api_upload_image():
    """رفع آمن عبر السيرفر (Firebase Admin SDK) — يحل محل الرفع المباشر من المتصفح
    الذي كان يسمح لأي زائر بالكتابة في Storage بلا أي مصادقة."""
    if "file" not in request.files:
        return err_json("No file provided")
    file = request.files["file"]
    if not file or not file.filename:
        return err_json("Empty file")
    allowed_ext = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    if not file.filename.lower().endswith(allowed_ext):
        return err_json("Unsupported file type")
    try:
        bucket    = fb_storage.bucket(FB_STORAGE_BUCKET)
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename)
        blob_path = f"{request.auth_uid}/{int(time.time()*1000)}_{safe_name}"
        blob      = bucket.blob(blob_path)
        blob.upload_from_file(file.stream, content_type=file.mimetype)
        blob.make_public()
        return ok_json({"url": blob.public_url})
    except Exception as e:
        logging.error(f"uploadImage error: {e}")
        return err_json("فشل رفع الصورة: " + str(e), 500)

# ── Bot Settings ──────────────────────────────────────────
@app.route("/api/getBotSettings", methods=["GET"])
@require_auth
@require_perm("bot")
def api_get_bot_settings():
    """يحل محل القراءة المباشرة لعقدة users كاملة من الفرونت إند (كانت تكشف بيانات كل التجار)."""
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
    existing = _fb_get(f"users/{username}") or {}
    updated  = {**existing, **d, "Username": username, "User_ID": uid}
    _fb_put(f"users/{username}", updated)
    with _settings_cache_lock:
        _settings_cache.clear()
    return ok_json(True)

# ── Conversations / Messages — إرسال واستقبال رسائل العملاء ──────────
@app.route("/api/getConversations", methods=["GET"])
@require_auth
@require_perm("messages")
def api_get_conversations():
    """قائمة محادثات العملاء لهذا التاجر، مرتبة بآخر رسالة أولاً."""
    uid = request.auth_uid
    raw = _fb_get(f"conversations_meta/{uid}") or {}
    result = []
    if isinstance(raw, dict):
        for sender_id, m in raw.items():
            if not isinstance(m, dict): continue
            result.append({
                "senderId": sender_id, "platform": m.get("platform",""),
                "lastMessage": m.get("lastMessage",""), "lastTimestamp": m.get("lastTimestamp",0),
                "lastDirection": m.get("lastDirection",""), "name": m.get("name","") or sender_id,
            })
    result.sort(key=lambda x: x.get("lastTimestamp",0), reverse=True)
    return ok_json(result)

@app.route("/api/getConversationMessages", methods=["GET"])
@require_auth
@require_perm("messages")
def api_get_conversation_messages():
    """سجل رسائل محادثة واحدة مرتب زمنياً (الأقدم أولاً) لعرضه في واجهة الدردشة."""
    uid = request.auth_uid
    sender_id = request.args.get("senderId","").strip()
    if not sender_id: return err_json("Missing senderId")
    raw = _fb_get(f"conversations/{uid}/{sender_id}") or {}
    items = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                row = dict(v); row["id"] = k
                items.append(row)
    items.sort(key=lambda x: x.get("timestamp", 0))
    return ok_json(items)

@app.route("/api/sendMessage", methods=["POST"])
@require_auth
@require_perm("messages")
def api_send_message():
    """يرسل رسالة يدوية من لوحة التحكم للعميل عبر نفس القناة (فيسبوك/إنستغرام/واتساب)
    التي راسل بها آخر مرة، باستخدام Meta Graph API — ويسجّلها في سجل المحادثة."""
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
    existing["plan"]         = plan
    existing["plan_updated"] = time.strftime("%Y-%m-%d %H:%M")
    _fb_put(f"users/{username}", existing)
    return ok_json({"plan": plan})

@app.route("/api/admin/createClient", methods=["POST"])
@require_admin
def api_admin_create_client():
    """إنشاء حساب جديد لعميل (محلي أو Fiverr) — يولّد User_ID فريد، يشفّر كلمة السر، ويهيّئ متجراً افتراضياً."""
    body     = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "").strip()
    store_name = str(body.get("storeName") or "").strip() or "متجري"
    plan     = str(body.get("plan") or "starter").strip().lower()
    source   = str(body.get("source") or "local").strip().lower()
    if source not in ("local", "fiverr"): source = "local"
    if not username or not password: return err_json("اسم المستخدم وكلمة السر مطلوبين")
    if plan not in PLANS: return err_json(f"خطة غير صحيحة: {list(PLANS.keys())}")
    if plan in ("lifetime", "full") and _count_lifetime_accounts() >= LIFETIME_MAX_SLOTS:
        return err_json(f"تم الوصول للحد الأقصى ({LIFETIME_MAX_SLOTS}) من عروض Lifetime", 409)
    if _fb_get(f"users/{username}"): return err_json("اسم المستخدم مستعمل من قبل", 409)
    new_uid = str(int(time.time() * 1000))
    _fb_put(f"users/{username}", {
        "Username": username, "Password": _hash_password(password),
        "User_ID": new_uid, "plan": plan, "source": source,
        "plan_updated": time.strftime("%Y-%m-%d %H:%M"),
    })
    _fb_put(f"data/{new_uid}/storeSettings", {
        "name": store_name, "tagline": "", "logo": "🛒", "lang": "AR", "currency": "DZD",
    })
    return ok_json({"username": username, "userId": new_uid,
                     "storeLink": f"{request.url_root.rstrip('/')}/?store={new_uid}"})

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
        """يسمح فقط بمسارات بيانات المستخدم المصادَق عليه — يمنع الوصول لبيانات تجار آخرين أو عقدة users/ الحساسة."""
        path = str(path or "")
        return path.startswith(f"data/{auth_uid}/") or path.startswith(f"ai_logs/{auth_uid}")

    # المسارات الخام (firebaseGet/Set/Update/Push) قوية جداً وتتجاوز نظام الصلاحيات المُجزّأة —
    # نقصرها على صاحب الحساب فقط، وعضو الفريق يستعمل مسارات /api المخصصة (المقيّدة بـ require_perm).
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
            _fb_put(payload["path"], payload.get("payload", payload.get("data")))
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
            limit   = max(1, min(int(payload.get("limit") or 200), 500))
            raw     = _fb_get(f"ai_logs/{auth_uid}") or {}
            items   = []
            if isinstance(raw, dict):
                for sender_id, msgs in raw.items():
                    if isinstance(msgs, dict):
                        for key, val in msgs.items():
                            if isinstance(val, dict):
                                row = dict(val)
                                row["id"] = key
                                row["sender_id"] = sender_id
                                items.append(row)
                    elif isinstance(msgs, dict):
                        msgs["id"] = sender_id
                        items.append(msgs)
            items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return ok_json(items[:limit])
        if action == "updateBotSettings":
            if not auth_username: return err_json("missing_username")
            data = payload.get("payload", payload.get("data")) or {}
            _fb_patch(f"users/{auth_username}", data)
            with _settings_cache_lock: _settings_cache.clear()
            return ok_json(True)
        return err_json("unknown_action")
    except Exception as e:
        logging.error(f"/api/saas: {e}")
        return err_json(str(e), 500)

# ── Facebook OAuth ────────────────────────────────────────
def get_user_settings(identifier):
    identifier = str(identifier or "").strip()
    if not identifier: return None
    with _settings_cache_lock:
        cached = _settings_cache.get(identifier)
        if cached and time.time() - cached["ts"] < _CACHE_TTL:
            return cached["data"]
    try:
        users = _fb_get("users")
        if not users: return None
        for _, data in users.items():
            if not isinstance(data, dict): continue
            ids = [str(data.get("page_id_FB") or "").strip(),
                   str(data.get("Page_ID_instgram") or "").strip(),
                   str(data.get("page_id_instagram") or "").strip(),
                   str(data.get("phone_number_id") or "").strip()]
            if identifier in ids:
                with _settings_cache_lock:
                    _settings_cache[identifier] = {"data": data, "ts": time.time()}
                return data
        return None
    except Exception as e:
        logging.error(f"get_user_settings: {e}"); return None

def _bot_allowed_for(bot_settings):
    """يتحقق أن خطة التاجر تسمح باستعمال البوت قبل معالجة أي رسالة — يمنع الرد
    على عملاء التجار اللي خطتهم ما فيهاش bot:True حتى لو ربطو صفحاتهم."""
    if not bot_settings: return False
    plan = str(bot_settings.get("plan", "starter")).lower()
    return PLANS.get(plan, {}).get("bot", False)

@app.route("/callback", methods=["GET"])
def fb_oauth_callback():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error: return _oauth_error_page(error)
    if not code or not state: return _oauth_error_page("Missing code or state")
    try:
        r1 = requests.get("https://graph.facebook.com/v19.0/oauth/access_token",
            params={"client_id":FB_APP_ID,"client_secret":FB_APP_SECRET_OAUTH,
                    "redirect_uri":REDIRECT_URI,"code":code}, timeout=15)
        r1.raise_for_status()
        short_token = r1.json().get("access_token")
        if not short_token: raise ValueError("No access_token")
        r2 = requests.get("https://graph.facebook.com/v19.0/oauth/access_token",
            params={"grant_type":"fb_exchange_token","client_id":FB_APP_ID,
                    "client_secret":FB_APP_SECRET_OAUTH,"fb_exchange_token":short_token}, timeout=15)
        r2.raise_for_status()
        long_token = r2.json().get("access_token", short_token)
        r3 = requests.get("https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token":long_token,"fields":"id,name,access_token,instagram_business_account"},
            timeout=15)
        r3.raise_for_status()
        pages = r3.json().get("data",[]) or []
        logging.info(f"📘 FB /me/accounts raw response: {pages}")
        fb_page_id = ig_page_id = ig_token = ""
        fb_token   = long_token
        pages_info = []
        for page in pages:
            fb_page_id = page.get("id","")
            fb_token   = page.get("access_token") or long_token
            pages_info.append({"type":"facebook","id":fb_page_id,"name":page.get("name","")})
            ig = page.get("instagram_business_account")
            if ig:
                ig_page_id = ig.get("id","")
                ig_token   = page.get("access_token") or long_token
                pages_info.append({"type":"instagram","id":ig_page_id,"name":f"{page.get('name','')} (IG)"})
            else:
                logging.warning(f"⚠️ Page '{page.get('name','')}' has NO instagram_business_account linked")
        uid = uname = ""
        try:
            sd    = jwt.decode(unquote(state), JWT_SECRET, algorithms=[JWT_ALGO])
            uid   = str(sd.get("uid","") or "").strip()
            uname = str(sd.get("uname","") or "").strip()
        except Exception as e:
            logging.error(f"OAuth state verification failed: {e}")
        if not uid: raise ValueError("UID missing or state invalid/expired")
        _fb_patch(f"data/{uid}/fbTokens", {
            "fb_access_token":fb_token,"fb_page_id":fb_page_id,
            "instgram_access_token":ig_token,"Page_ID_instgram":ig_page_id,
            "pages":pages_info,"connected":True,"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        if uname:
            _fb_patch(f"users/{uname}", {
                "fb_access_token":fb_token,"page_id_FB":fb_page_id,
                "instgram_access_token":ig_token,"Page_ID_instgram":ig_page_id,
            })
        logging.info(f"✅ OAuth OK UID={uid}")
        ph = "".join(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px'>"
                     f"<span>{'📷' if p['type']=='instagram' else '📘'}</span>"
                     f"<span>{p.get('name','—')}</span></div>" for p in pages_info)
        return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><title>تم الربط</title>
<style>body{{margin:0;font-family:Arial;background:#0a1628;color:#e8edf5;display:flex;align-items:center;justify-content:center;min-height:100vh;}}</style></head>
<body><div style="text-align:center;padding:40px;background:rgba(15,32,68,.92);border:1px solid rgba(0,214,143,.3);border-radius:16px;max-width:340px">
<div style="font-size:56px">✅</div><h2 style="color:#00d68f">تم الربط بنجاح!</h2>
<p style="color:#8899bb;font-size:13px">جاري إغلاق النافذة...</p>
{('<div style="margin-top:16px;background:rgba(255,255,255,.04);border-radius:10px;padding:12px">' + ph + '</div>') if ph else ''}
</div><script>try{{window.opener&&window.opener.postMessage({{type:"FB_AUTH_SUCCESS",
fb_token:{json.dumps(fb_token)},ig_token:{json.dumps(ig_token)},
fb_page_id:{json.dumps(fb_page_id)},ig_page_id:{json.dumps(ig_page_id)}}},"*");}}catch(e){{}}
setTimeout(()=>window.close(),2500);</script></body></html>"""
    except Exception as err:
        logging.error(f"OAuth error: {err}"); return _oauth_error_page(str(err))

def _oauth_error_page(msg):
    return f"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><title>فشل</title>
<style>body{{margin:0;font-family:Arial;background:#0a1628;color:#e8edf5;display:flex;align-items:center;justify-content:center;min-height:100vh;}}</style></head>
<body><div style="text-align:center;padding:40px;background:rgba(15,32,68,.92);border:1px solid rgba(255,77,109,.3);border-radius:16px;max-width:340px">
<div style="font-size:56px">❌</div><h2 style="color:#ff4d6d">فشل الربط</h2>
<p style="color:#8899bb;font-size:12px;word-break:break-all">{msg}</p>
</div><script>window.opener&&window.opener.postMessage({{type:"FB_AUTH_ERROR",message:{json.dumps(msg)}}},"*");
setTimeout(()=>window.close(),4000);</script></body></html>"""

@app.route("/api/getOAuthState", methods=["GET"])
@require_auth
@require_owner
def api_get_oauth_state():
    """state موقّع بـ JWT (صلاحية 10 دقائق) بدل JSON عادي قابل للتزوير من أي زائر يعرف الـ uid."""
    state = jwt.encode({
        "uid": request.auth_uid, "uname": request.auth_username,
        "exp": int(time.time()) + 600,
    }, JWT_SECRET, algorithm=JWT_ALGO)
    return ok_json({"state": state})

@app.route("/fb-status", methods=["GET"])
@require_auth
@require_owner
def fb_status():
    uid  = request.auth_uid
    data = _fb_get(f"data/{uid}/fbTokens")
    if data and isinstance(data,dict) and data.get("connected"):
        return jsonify({"connected":True,"updated_at":data.get("updated_at","—"),"pages":data.get("pages",[])})
    return jsonify({"connected":False})

@app.route("/fb-disconnect", methods=["POST"])
@require_auth
@require_owner
def fb_disconnect():
    uid = request.auth_uid
    _fb_patch(f"data/{uid}/fbTokens", {"connected":False,"fb_access_token":"",
        "instgram_access_token":"","pages":[],"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S")})
    return jsonify({"status":"ok"})

# ── Bot / Webhook ─────────────────────────────────────────
def meta_post(url, payload, headers=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.ok:
                logging.info(f"✅ meta_post OK → {url}")
                return True
            logging.error(f"❌ meta_post FAILED [{r.status_code}] → {url} | response={r.text[:500]}")
            if r.status_code in (400,401,403): return False
        except Exception as e:
            logging.error(f"meta_post attempt {attempt+1}: {e}")
        sleep(1.5)
    return False

def send_facebook_message(recipient_id, text, access_token, page_id=None):
    if not access_token:
        logging.error(f"send_facebook_message: NO access_token for recipient {recipient_id}")
        return False
    if not recipient_id or not text:
        logging.error(f"send_facebook_message: missing recipient_id or text")
        return False
    url = (f"https://graph.facebook.com/v21.0/{page_id}/messages"
           if page_id else "https://graph.facebook.com/v21.0/me/messages")
    logging.info(f"📤 Sending FB message to {recipient_id} via page {page_id}")
    return meta_post(url, {"recipient":{"id":recipient_id},"message":{"text":text[:2000]},"access_token":access_token})

def send_whatsapp_message(phone_number_id, recipient_id, text, token):
    if not token or not text: return False
    return meta_post(f"https://graph.facebook.com/v21.0/{phone_number_id}/messages",
        {"messaging_product":"whatsapp","to":recipient_id,"type":"text","text":{"body":text[:2000]}},
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"})

def get_media_url(media_id, access_token):
    try:
        r = requests.get(f"https://graph.facebook.com/v21.0/{media_id}",
                         params={"access_token":access_token}, timeout=10)
        return r.json().get("url","") if r.ok else ""
    except Exception: return ""

def download_media(url, access_token):
    try:
        r = requests.get(url, headers={"Authorization":f"Bearer {access_token}"}, timeout=20)
        return r.content if r.ok else b""
    except Exception: return b""

def _gemini_generate_with_fallback(api_key, contents, config, label=""):
    last_err = None
    for model in _GEMINI_MODELS:
        for attempt in range(2):
            try:
                client = genai.Client(api_key=api_key, http_options={"api_version":"v1beta"})
                base_max_tokens = getattr(config, "max_output_tokens", 1024) or 1024
                cfg_dict = {
                    "temperature": getattr(config, "temperature", 0.7),
                    "max_output_tokens": max(base_max_tokens, 2048),
                }
                sys_instr = getattr(config, "system_instruction", None)
                if sys_instr:
                    cfg_dict["system_instruction"] = sys_instr
                if "2.5" in model:
                    cfg_dict["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
                cfg = types.GenerateContentConfig(**cfg_dict)
                response = client.models.generate_content(model=model, contents=contents, config=cfg)

                text = ""
                finish_reason = None
                if response and response.candidates:
                    cand = response.candidates[0]
                    finish_reason = getattr(cand, "finish_reason", None)
                    if cand.content and cand.content.parts:
                        for part in cand.content.parts:
                            t = getattr(part, "text", "") or ""
                            if t: text += t
                if not text:
                    try: text = response.text or ""
                    except Exception: pass
                text = text.strip()

                if not text:
                    pf = getattr(response, "prompt_feedback", None)
                    logging.warning(
                        f"Gemini {model} EMPTY | finish_reason={finish_reason} | "
                        f"prompt_feedback={pf} | candidates_count={len(response.candidates) if response and response.candidates else 0}"
                    )
                    raise ValueError(f"Empty response (finish_reason={finish_reason})")
                return text, model
            except Exception as e:
                last_err = e
                if "404" in str(e) or "NOT_FOUND" in str(e): break
                sleep(1.5)
    raise RuntimeError(f"All Gemini models failed: {last_err}")

def get_history(sender_id):
    try:
        data = _firebase_ref(f"chats/{sender_id}").get()
        if not data: return []
        hist = sorted(data.values(), key=lambda x: x.get("timestamp",0))
        return hist[-(MAX_HISTORY_TURNS*2):]
    except Exception: return []

def save_history(sender_id, user_msg, bot_msg):
    try:
        ref = _firebase_ref(f"chats/{sender_id}")
        now = time.time()
        ref.push({"role":"user","content":user_msg,"timestamp":now})
        ref.push({"role":"assistant","content":bot_msg,"timestamp":now+0.001})
    except Exception as e:
        logging.error(f"save_history: {e}")

def history_to_text(history):
    lines = []
    for t in history:
        prefix = "العميل" if t.get("role")=="user" else "البوت"
        lines.append(f"{prefix}: {t.get('content','')}")
    return "\n".join(lines)

def log_ai_message(sender_id, user_msg, bot_msg, platform="FB", merchant_uid=""):
    try:
        path = f"ai_logs/{merchant_uid}/{sender_id}" if merchant_uid else f"ai_logs/{sender_id}"
        _firebase_ref(path).push({
            "user_message":user_msg,"bot_reply":bot_msg,"platform":platform,
            "timestamp":time.time(),"date":time.strftime("%Y-%m-%d %H:%M:%S"),
            "sender_id":sender_id,
        })
    except Exception as e:
        logging.error(f"log_ai_message: {e}")

def _log_conversation(uid, sender_id, direction, text, platform, via="", page_id="", name=""):
    """يسجّل رسالة (واردة أو صادرة) في سجل محادثة موحّد لكل عميل، ويحدّث ملخّص المحادثة
    (آخر رسالة، القناة، معرّف الصفحة/الرقم المستعمل) — يغذّي واجهة 'المحادثات' الجديدة
    بدون أي تأثير على ai_logs أو chats الموجودة مسبقاً."""
    if not uid or not sender_id:
        return
    now = time.time()
    entry = {
        "direction": direction, "text": (text or "")[:2000], "platform": platform,
        "timestamp": now, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if via: entry["via"] = via
    try:
        _firebase_ref(f"conversations/{uid}/{sender_id}").push(entry)
        meta_patch = {
            "lastMessage": (text or "")[:200], "lastTimestamp": now,
            "lastDirection": direction, "platform": platform,
        }
        if page_id: meta_patch["pageId"] = page_id
        if name: meta_patch["name"] = name
        existing_meta = _fb_get(f"conversations_meta/{uid}/{sender_id}")
        if existing_meta:
            _fb_patch(f"conversations_meta/{uid}/{sender_id}", meta_patch)
        else:
            meta_patch.setdefault("name", name or sender_id)
            _fb_put(f"conversations_meta/{uid}/{sender_id}", meta_patch)
    except Exception as e:
        logging.error(f"_log_conversation: {e}")

def get_products_text(bot_settings):
    try:
        uid      = bot_settings.get("User_ID")
        products = _fb_get(f"data/{uid}/products") if uid else None
        if products and isinstance(products, dict):
            lines = [f"- {p.get('name','?')}: {p.get('sell','?')} | stock:{p.get('available','?')} | {p.get('category','')}".strip()
                     for p in products.values() if isinstance(p,dict)]
            if lines: return "\n".join(lines)
    except Exception: pass
    return bot_settings.get("products_info","")

def extract_json(full_text):
    try:
        match = re.search(rf"{re.escape(_JSON_START)}(.*?){re.escape(_JSON_END)}", full_text, re.DOTALL)
        if match:
            return json.loads(match.group(1).strip()), full_text.split(_JSON_START)[0].strip()
    except Exception: pass
    return None, full_text

def _find_field(order_data, *exact_keys):
    for k in exact_keys:
        v = order_data.get(k)
        if v: return v
    for key, val in order_data.items():
        key_l = str(key).strip()
        for target in exact_keys:
            if target and target in key_l and val:
                return val
    return ""

def _normalize_delivery_type(raw):
    """يحوّل أي صياغة حرة (عربي/فرنسي) لنوع التوصيل إلى home أو desk بشكل موحّد."""
    raw = str(raw or "").strip().lower()
    desk_keywords = ["مكتب", "ستوب ديسك", "ستوب دسك", "stop desk", "stopdesk", "bureau",
                      "نقطة استلام", "office", "agence", "وكالة"]
    for kw in desk_keywords:
        if kw in raw:
            return "desk"
    return "home"

def validate_order(order_data):
    if not order_data or not isinstance(order_data,dict): return False,"لا توجد بيانات"
    product = _find_field(order_data, "product", "product_name", "المنتج", "اسم المنتج")
    if not product or str(product).strip() in ("","null","None"): return False,"اسم المنتج غير موجود"
    qty = _find_field(order_data, "quantity", "qty", "الكمية")
    if not qty or str(qty).strip() in ("","null","0"): return False,"الكمية غير محددة"
    name = _find_field(order_data, "name", "الاسم", "اسم")
    if not name: return False,"اسم العميل غير موجود"
    phone = _find_field(order_data, "phone", "الهاتف", "هاتف")
    if not phone: return False,"رقم الهاتف غير موجود"
    city = _find_field(order_data, "city", "المدينة", "مدينة")
    if not city: return False,"المدينة غير موجودة"
    delivery = _find_field(order_data, "delivery_type", "نوع التوصيل", "التوصيل")
    if not delivery: return False,"نوع التوصيل غير محدد (منزل أو مكتب الاستلام)"
    return True,""

def save_order_from_bot(order_data, bot_settings, sender_id=""):
    try:
        uid = bot_settings.get("User_ID")
        if not uid: return False
        qty_raw = _find_field(order_data, "quantity", "qty", "الكمية") or 1
        try: qty_val = int(re.sub(r"\D","",str(qty_raw)) or 1)
        except Exception: qty_val = 1
        phone   = _find_field(order_data, "phone", "الهاتف", "هاتف")
        product = _find_field(order_data, "product", "product_name", "المنتج", "اسم المنتج")
        delivery_type = _normalize_delivery_type(_find_field(order_data, "delivery_type", "نوع التوصيل", "التوصيل"))

        # ✅ منع التكرار: لو نفس المحادثة سجّلت طلب لنفس الهاتف/المنتج مؤخراً، لا ننشئ طلباً جديداً
        if sender_id and _is_duplicate_bot_order(sender_id, phone, product):
            logging.info(f"⏭️ تجاهل طلب مكرر من البوت | sender={sender_id} | product={product}")
            return False

        # ✅ سقف الطلبات الشهري الموحّد (يدوي + متجر + بوت معاً) لخطط Lifetime/Full
        if not _under_cap(uid, "orderCount", "orderCap"):
            logging.warning(f"⏭️ تجاوز سقف الطلبات الشهري | uid={uid}")
            return False

        order_id = f"ORD-{int(time.time()*1000)}"
        order    = {
            "id":order_id,"date":time.strftime("%Y-%m-%d %H:%M"),"status":"Pending",
            "profit":0,"source":"bot","date_sent":"","date_delivered":"","deliveryType":delivery_type,
            "name":   _find_field(order_data, "name", "الاسم", "اسم"),
            "phone":  phone,
            "product":product,
            "qty":    qty_val,
            "city":   _find_field(order_data, "city", "المدينة", "مدينة"),
            "address":_find_field(order_data, "address", "العنوان", "عنوان"),
            "unitPrice":0,"shipping":0,"total":0,
        }
        p_data = _fb_get(f"data/{uid}/products/{order['product']}")
        c_data = _fb_get(f"data/{uid}/cities/{order['city']}")
        if p_data: order["unitPrice"] = float(p_data.get("sell",0))
        if c_data:
            ship_cust, _ = _ship_values(c_data, delivery_type)
            order["shipping"] = ship_cust
        order["total"] = (order["unitPrice"]*order["qty"]) + order["shipping"]
        _fb_put(f"data/{uid}/orders/{order_id}", order)
        _increment_usage(uid, "orderCount")
        if sender_id: _mark_bot_order(sender_id, phone, product)
        logging.info(f"✅ Bot order saved: {order_id}")
        return True
    except Exception as e:
        logging.error(f"save_order_from_bot: {e}")
        return False

def ask_gemini(sender_id, user_message, bot_settings,
               media_bytes=b"", mime_type="", is_voice=False, is_image=False):
    api_key = str(bot_settings.get("Gemini_api_key") or "").strip()
    if not api_key: return "مفتاح الذكاء الاصطناعي غير موجود.", None
    if is_voice and media_bytes:
        try:
            contents = [types.Part.from_bytes(data=media_bytes,mime_type=mime_type),
                        types.Part.from_text(text="استمع وحوّل إلى نص فقط.")]
            text, _ = _gemini_generate_with_fallback(api_key, contents,
                      types.GenerateContentConfig(temperature=0.1,max_output_tokens=512),"audio")
            user_message = text; media_bytes = b""
        except Exception:
            user_message = "[لم أتمكن من فهم الرسالة الصوتية]"; media_bytes = b""
    if is_image and media_bytes:
        try:
            contents = [types.Part.from_bytes(data=media_bytes,mime_type=mime_type),
                        types.Part.from_text(text=f"صف هذه الصورة من منظور مبيعات. {user_message or ''}")]
            desc, _ = _gemini_generate_with_fallback(api_key, contents,
                     types.GenerateContentConfig(temperature=0.2,max_output_tokens=256),"image")
            user_message = f"{user_message}\n[وصف الصورة: {desc}]" if user_message else f"[وصف الصورة: {desc}]"
            media_bytes = b""
        except Exception: pass
    if not user_message.strip(): user_message = "[رسالة فارغة]"
    if len(user_message) > 1500: user_message = user_message[:1500]
    try:
        instructions = bot_settings.get("AI_instructions","أنت مساعد مبيعات ذكي.")
        products     = get_products_text(bot_settings)
        history_text = history_to_text(get_history(sender_id))
        req_format = '{"product":"اسم المنتج","quantity":"الكمية","name":"اسم العميل","phone":"رقم الهاتف","city":"المدينة","delivery_type":"منزل أو مكتب الاستلام","address":"العنوان"}'
        system_text = f"""أنت مساعد مبيعات لمتجر إلكتروني. مهمتك مساعدة العملاء في الطلب.
رد بنفس لغة العميل (عربي أو فرنسي).
اجمع من العميل بشكل ودي: الاسم الكامل، الهاتف، المدينة، اسم المنتج، الكمية، العنوان، **ونوع التوصيل الذي يفضّله العميل بنفسه (توصيل للمنزل، أو توصيل لمكتب الاستلام/Stop Desk)** — اسأله بوضوح عن هذا الخيار ولا تفترضه أبداً من نفسك. لا تكتب تأكيد الطلب قبل جمع كل هذه المعلومات.
تعليمات إضافية من المتجر:
{instructions}

قائمة المنتجات المتوفرة:
{products or "لا توجد منتجات مسجلة حالياً."}

عندما تجمع كل المعلومات المطلوبة من العميل (الاسم والهاتف والمدينة والمنتج والكمية ونوع التوصيل والعنوان)، أضف في نهاية ردك مباشرة (بدون أي نص بعدها) كتلة JSON بهذا الشكل بالضبط، باستخدام نفس أسماء المفاتيح الإنجليزية product, quantity, name, phone, city, delivery_type, address (لا تترجم أسماء المفاتيح، فقط القيم بالعربي أو الفرنسي، وقيمة delivery_type تكون "منزل" أو "مكتب"):
{_JSON_START}
{req_format}
{_JSON_END}

⚠️ مهم جداً: إذا كان سجل المحادثة السابق يُظهر أنك سبق وأرسلت كتلة JSON بهذا الشكل لهذا العميل بنفس المنتج، فلا تكررها أبداً في أي رد لاحق — فقط أكّد له بأدب أن طلبه مسجّل ومتابَع، بدون أي كتلة JSON جديدة.
"""
        history_block = f"سجل المحادثة السابق:\n{history_text}\n\n" if history_text else ""
        user_text_block = f"{history_block}رسالة العميل الحالية: {user_message}"

        contents = [types.Part.from_text(text=user_text_block)]
        config   = types.GenerateContentConfig(
            temperature=0.7, max_output_tokens=1024,
            system_instruction=system_text,
        )
        full_text, _ = _gemini_generate_with_fallback(api_key,contents,config,f"chat:{sender_id}")
        order_data, clean_text = extract_json(full_text)
        if order_data:
            logging.info(f"📦 JSON extracted for {sender_id}: {order_data}")
            is_valid, reason = validate_order(order_data)
            if not is_valid:
                logging.warning(f"⚠️ Order invalid for {sender_id}: {reason}")
                try:
                    retry_text, _ = _gemini_generate_with_fallback(api_key,
                        [types.Part.from_text(text=f'العميل: "{user_message}"\nالناقص: {reason}\nاسأل بلطف.')],
                        types.GenerateContentConfig(temperature=0.5,max_output_tokens=512),"retry")
                    clean_text = retry_text
                except Exception: pass
                order_data = None
        save_history(sender_id, user_message, clean_text)
        log_ai_message(sender_id, user_message, clean_text, merchant_uid=str(bot_settings.get("User_ID","")))
        return clean_text, order_data
    except Exception as e:
        logging.error(f"ask_gemini {sender_id}: {e}")
        return "عذراً، حاول مرة أخرى بعد قليل.", None

def process_bg(sender_id, user_text, bot, send_fn,
               media_bytes=b"", mime_type="", is_voice=False, is_image=False, platform="fb", page_id=""):
    def task():
        logging.info(f"🔄 process_bg START | sender={sender_id} | platform={platform} | text={user_text[:80]!r}")
        try:
            merchant_uid = bot.get("User_ID", "")
            if merchant_uid and not _under_cap(merchant_uid, "botMsgCount", "botMsgCap"):
                logging.warning(f"⏭️ تجاوز سقف رسائل البوت الشهري | uid={merchant_uid} — لا يتم استدعاء Gemini")
                try: send_fn("عذراً، تم الوصول للحد الشهري لخدمة المساعد الذكي. سيتم التواصل معك يدوياً قريباً 🙏")
                except Exception: pass
                return
            if merchant_uid: _increment_usage(merchant_uid, "botMsgCount")
            reply, order = ask_gemini(sender_id,user_text,bot,
                                      media_bytes=media_bytes,mime_type=mime_type,
                                      is_voice=is_voice,is_image=is_image)
            logging.info(f"🤖 ask_gemini DONE | sender={sender_id} | reply_len={len(reply or '')} | order={'yes' if order else 'no'}")
            if order and (not reply or not reply.strip()):
                reply = "✅ تم استلام طلبك بنجاح! سنتواصل معك قريباً لتأكيد التوصيل."
            elif not reply or not reply.strip():
                reply = "عذراً، لم أتمكن من المعالجة الآن. حاول مرة أخرى."
            try:
                ok = send_fn(reply)
                logging.info(f"📨 send_fn result for {sender_id}: {ok}")
                if ok and merchant_uid:
                    _log_conversation(merchant_uid, sender_id, "out", reply, platform, via="bot", page_id=page_id)
            except Exception as send_err:
                logging.error(f"send_fn raised exception ({sender_id}): {send_err}")
            if order:
                save_order_from_bot(order, bot, sender_id)
        except Exception as e:
            logging.error(f"BG task ({sender_id}): {e}", exc_info=True)
            try: send_fn("عذراً، حدث خطأ مؤقت.")
            except Exception: pass
    _executor.submit(task)

def verify_sig(raw_body, headers):
    if not META_APP_SECRET: return True
    sig = headers.get("X-Hub-Signature-256","")
    if not sig.startswith("sha256="): return False
    expected = hmac.new(META_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig[7:])

@app.before_request
def limit_size():
    if request.content_length and request.content_length > MAX_PAYLOAD_SIZE:
        abort(413)

_STICKERS   = ["😊 أهلاً! كيف يمكنني مساعدتك؟","👋 مرحباً! يسعدنا خدمتك.","❤️ شكراً لتواصلك!"]
_sticker_i  = 0
_sticker_lk = threading.Lock()

def sticker_reply():
    global _sticker_i
    with _sticker_lk:
        r = _STICKERS[_sticker_i % len(_STICKERS)]; _sticker_i += 1
    return r

@app.route("/webhook", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge",""), 200
        return "Forbidden", 403
    raw_body = request.get_data()
    if not verify_sig(raw_body, request.headers): return "Forbidden", 403
    data = request.get_json(silent=True)
    if not data: return "Bad Request", 400
    logging.info(f"📩 webhook RECEIVED: object={data.get('object')} | entries={len(data.get('entry',[]))}")
    def handle(payload):
        try:
            for entry in payload.get("entry",[]) or []:
                if "changes" in entry:
                    for change in entry.get("changes",[]) or []:
                        val = change.get("value",{})
                        if "messages" not in val: continue
                        phone_id = val.get("metadata",{}).get("phone_number_id","")
                        bot      = get_user_settings(phone_id)
                        if not bot: continue
                        if not _bot_allowed_for(bot):
                            logging.info(f"⏭️ webhook(wa): خطة التاجر لا تدعم البوت | phone_id={phone_id}")
                            continue
                        wa_tok = str(bot.get("whtsapp_token") or "").strip()
                        if not wa_tok: continue
                        merchant_uid_wa = bot.get("User_ID", "")
                        for msg in val.get("messages",[]) or []:
                            sid=msg.get("from",""); mtype=msg.get("type","")
                            utxt=""; mdata=b""; mime=""; isvoc=isimg=False
                            if mtype=="text":
                                utxt=msg.get("text",{}).get("body","").strip()
                            elif mtype in ("audio","voice"):
                                isvoc=True; obj=msg.get("audio") or msg.get("voice") or {}
                                mid=obj.get("id","")
                                if mid:
                                    murl=get_media_url(mid,wa_tok)
                                    if murl: mdata=download_media(murl,wa_tok); mime=obj.get("mime_type","audio/ogg").split(";")[0].strip()
                            elif mtype=="image":
                                isimg=True; obj=msg.get("image",{}); utxt=obj.get("caption",""); mid=obj.get("id","")
                                if mid:
                                    murl=get_media_url(mid,wa_tok)
                                    if murl: mdata=download_media(murl,wa_tok); mime=obj.get("mime_type","image/jpeg")
                            elif mtype=="sticker":
                                def _s(reply,_sid=sid,_pid=phone_id,_tok=wa_tok): return send_whatsapp_message(_pid,_sid,reply,_tok)
                                _executor.submit(lambda fn=_s: fn(sticker_reply())); continue
                            if not utxt and not mdata: continue
                            log_text_wa = utxt or ("🎙️ [رسالة صوتية]" if isvoc else "🖼️ [صورة]" if isimg else "")
                            if merchant_uid_wa:
                                _log_conversation(merchant_uid_wa, sid, "in", log_text_wa, "wa", page_id=phone_id)
                            if is_rate_limited(sid,"wa"): continue
                            def wa_fn(reply,_sid=sid,_pid=phone_id,_tok=wa_tok): return send_whatsapp_message(_pid,_sid,reply,_tok)
                            process_bg(sid,utxt,bot,wa_fn,mdata,mime,isvoc,isimg,"wa",phone_id)
                elif "messaging" in entry:
                    page_id=str(entry.get("id","") or "").strip()
                    bot=get_user_settings(page_id)
                    if not bot:
                        logging.warning(f"⚠️ webhook: NO merchant found for page_id={page_id}")
                        continue
                    if not _bot_allowed_for(bot):
                        logging.info(f"⏭️ webhook(fb): خطة التاجر لا تدعم البوت | page_id={page_id}")
                        continue
                    fb_pid = str(bot.get("page_id_FB") or "").strip()
                    ig_pid = str(bot.get("Page_ID_instgram") or bot.get("page_id_instagram") or "").strip()
                    if page_id == ig_pid and ig_pid:
                        tok = str(bot.get("instgram_access_token") or "").strip()
                        is_instagram = True
                    elif page_id == fb_pid and fb_pid:
                        tok = str(bot.get("fb_access_token") or "").strip()
                        is_instagram = False
                    else:
                        tok = str(bot.get("fb_access_token") or bot.get("instgram_access_token") or "").strip()
                        is_instagram = False
                        logging.warning(f"⚠️ webhook: page_id={page_id} didn't match fb_pid={fb_pid} or ig_pid={ig_pid} exactly")
                    if not tok:
                        logging.warning(f"⚠️ webhook: merchant found (User_ID={bot.get('User_ID')}) but NO access token for page_id={page_id} (is_instagram={is_instagram})")
                        continue
                    # ✅ Instagram Messaging API يرفض الإرسال إذا استُعمل معرف حساب إنستغرام (ig_pid) بالرابط —
                    # Meta تفرض استعمال معرف صفحة فيسبوك (fb_pid) أو الكلمة "me" مع توكن الصفحة، وإلا يرجع خطأ (#3).
                    send_pid = (fb_pid or None) if is_instagram else page_id
                    logging.info(f"🔑 Using {'Instagram' if is_instagram else 'Facebook'} token for page_id={page_id} | send_pid={send_pid or 'me'}")
                    platform_str = "ig" if is_instagram else "fb"
                    merchant_uid_fb = bot.get("User_ID", "")
                    msging_list = entry.get("messaging",[]) or []
                    logging.info(f"📋 messaging entries count: {len(msging_list)}")
                    for me in msging_list:
                        sid=me.get("sender",{}).get("id","")
                        logging.info(f"👤 processing message from sid={sid} | raw={me}")
                        if not sid or sid==page_id:
                            logging.info(f"⏭️ skipped: sid empty or equals page_id")
                            continue
                        utxt=""; mdata=b""; mime=""; isvoc=isimg=False
                        if "message" in me and not me["message"].get("is_echo"):
                            msg=me["message"]
                            if "text" in msg: utxt=msg["text"].strip()
                            elif "attachments" in msg:
                                for att in msg.get("attachments",[]) or []:
                                    atype=att.get("type",""); pload=att.get("payload",{}); murl=pload.get("url","")
                                    if atype in ("audio","voice"):
                                        isvoc=True; mime="audio/mpeg"
                                        if murl: mdata=download_media(murl,tok)
                                    elif atype=="image":
                                        isimg=True; mime="image/jpeg"
                                        if murl: mdata=download_media(murl,tok)
                                    elif atype=="sticker":
                                        def _sf(reply,_sid=sid,_tok=tok,_pid=page_id): return send_facebook_message(_sid,reply,_tok,page_id=_pid)
                                        _executor.submit(lambda fn=_sf: fn(sticker_reply()))
                        elif "postback" in me:
                            utxt=me["postback"].get("title") or me["postback"].get("payload","")
                        if not utxt and not mdata:
                            # حدث بلا محتوى (مثلاً message_edit، read receipt...) — يُتجاهل بلا لمس عداد الـ rate limit،
                            # لأن لمسه هنا كان يحرق نافذة الـ 2 ثواني ويخلي الرسالة الحقيقية التالية تنرفض كـ"rate limited"
                            # ويبقى البوت ساكت (هذا كان سبب توقف الرد على إنستغرام).
                            logging.info(f"⏭️ skipped: no text/media extracted from message (utxt empty, mdata empty) | me={me}")
                            continue
                        log_text_fb = utxt or ("🎙️ [رسالة صوتية]" if isvoc else "🖼️ [صورة]" if isimg else "")
                        if merchant_uid_fb:
                            _log_conversation(merchant_uid_fb, sid, "in", log_text_fb, platform_str, page_id=(send_pid or page_id))
                        if is_rate_limited(sid,"fb"):
                            logging.info(f"⏭️ skipped: rate limited for sid={sid}")
                            continue
                        def fb_fn(reply,_sid=sid,_tok=tok,_pid=send_pid): return send_facebook_message(_sid,reply,_tok,page_id=_pid)
                        process_bg(sid,utxt,bot,fb_fn,mdata,mime,isvoc,isimg,platform_str,(send_pid or page_id))
        except Exception as e:
            logging.error(f"handle() error: {e}")
    _executor.submit(handle, data)
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)