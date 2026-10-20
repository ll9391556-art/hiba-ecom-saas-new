# -*- coding: utf-8 -*-
"""الأمان: JWT والـ decorators، كلمات السر، حدود المعدل (محلية ومشتركة عبر Firebase)،
التشفير (Fernet)، وحماية SSRF مع تثبيت DNS. منقول من app.py بلا تغيير (Phase 4 / A3).
app.py يعاود يصدّر نفس الأسماء."""
import hashlib
import hmac
import ipaddress
import logging
import socket
import threading
import time

import urllib3
from functools import wraps
from time import sleep
from urllib.parse import urlparse

import bcrypt
import jwt
import requests
from cryptography.fernet import InvalidToken
from flask import request
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.poolmanager import PoolManager

from core.config import (ADMIN_API_KEY, JWT_ALGO, JWT_EXPIRY_HOURS_MEMBER, JWT_EXPIRY_HOURS_OWNER,
                         JWT_SECRET, TEAM_PERM_KEYS, _fernet)
from core.db import _fb_delete, _fb_get, _fb_keys, _firebase_ref
from core.http import err_json
from core.util import _safe_int

def _encrypt_secret(text):
    return _fernet.encrypt(str(text).encode()).decode()


def _decrypt_secret(token):
    try:
        return _fernet.decrypt(str(token).encode()).decode()
    except (InvalidToken, Exception):
        return None


def issue_token(uid, username, role="owner", perms=None, member_username="", member_name=""):
    """يولّد JWT لصاحب الحساب (owner) أو لعضو فريق (member)."""
    expiry_hours = JWT_EXPIRY_HOURS_MEMBER if role == "member" else JWT_EXPIRY_HOURS_OWNER
    payload = {
        "uid": str(uid), "username": str(username), "role": role, "typ": "session",
        "iat": int(time.time()), "exp": int(time.time()) + expiry_hours * 3600,
    }
    if role == "member":
        payload["perms"]           = perms or {}
        payload["memberUsername"]  = member_username
        payload["memberName"]      = member_name or member_username
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token, typ="session"):
    """يفك JWT ويتأكد من نوعه: "session" (تسجيل الدخول) أو "oauth_state" (ربط فيسبوك).
    أي توكن بلا typ صالح، أو بنوع آخر، يترفض دائماً — بلا هاد الفحص، state ديال OAuth
    كان يخدم كجلسة owner لمدة 10 دقائق."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        return None
    return payload if payload.get("typ") == typ else None


def _extract_bearer(req):
    h = req.headers.get("Authorization", "")
    return h.split(" ", 1)[1].strip() if h.lower().startswith("bearer ") else ""


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _extract_bearer(request)
        payload = decode_token(token) if token else None
        if not payload or not payload.get("uid"):
            return err_json("Unauthorized — يرجى تسجيل الدخول من جديد", 401)

        role = payload.get("role", "owner")

        # ── تحديث فوري لحالة/صلاحيات عضو الفريق من قاعدة البيانات ──
        # قبل: active/permissions كانا يُقرآن فقط من داخل الـ JWT نفسه (لقطة
        # لحظة تسجيل الدخول)، فإذا التاجر عطّل العضو أو غيّر صلاحياته أو حذفه
        # نهائياً، التوكن القديم يبقى صالح بنفس الصلاحيات القديمة لمدة تصل
        # لـ 7 أيام (JWT_EXPIRY_HOURS) — نافذة خطيرة لموظف مطرود مثلاً.
        # الآن: كل طلب من عضو فريق يتحقق فوراً من team_users/{username} —
        # إذا العضو محذوف أو معطّل، التوكن يُرفض فوراً بلا انتظار انتهاء صلاحيته.
        if role == "member":
            member_username = payload.get("memberUsername", "")
            member = _fb_get(f"team_users/{member_username}") if member_username else None
            if not member or not isinstance(member, dict):
                return err_json("هذا الحساب لم يعد موجوداً — يرجى تسجيل الدخول من جديد", 401)
            if not member.get("active", True):
                return err_json("هذا الحساب معطّل حالياً — تواصل مع صاحب المتجر", 403)
            # التأكد أن العضو ما زال تابعاً لنفس صاحب الحساب (uid) الموجود بالتوكن —
            # حماية إضافية لو انحذف الحساب الأصلي وانخلق يوزرنيم بنفس الاسم لاحقاً.
            if str(member.get("ownerUid", "")) != str(payload["uid"]):
                return err_json("Unauthorized", 401)
            request.auth_perms = _clean_perms(member.get("permissions"))
            request.auth_member_name = member.get("name", member_username)
        else:
            request.auth_perms = {}
            request.auth_member_name = ""

        request.auth_uid             = payload["uid"]
        request.auth_username        = payload.get("username", "")
        request.auth_role            = role
        request.auth_member_username = payload.get("memberUsername", "")
        return f(*args, **kwargs)
    return wrapper


def require_perm(perm):
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
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key", "").strip()
        # request.remote_addr مُصحَّح الآن عبر ProxyFix (بروكسي موثوق واحد) بدل الوثوق
        # بهيدر X-Forwarded-For الخام القادم من العميل مباشرة.
        client_ip = request.remote_addr or ""
        if _login_rate_limited(f"admin:{client_ip}", max_attempts=10, window=300):
            return err_json("محاولات كثيرة جداً — حاول لاحقاً", 429)
        # مقارنة زمن-ثابت (constant-time) بدل != العادية، لمنع هجوم قياس التوقيت (timing attack)
        if not ADMIN_API_KEY or not hmac.compare_digest(key, ADMIN_API_KEY):
            return err_json("Forbidden", 403)
        return f(*args, **kwargs)
    return wrapper


def require_owner(f):
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
    # توافق مرحلي مع كلمات السر القديمة غير المُجزّأة — compare_digest بدل == العادية
    # لتفادي كشف طول/محتوى كلمة السر عبر فروقات التوقيت (timing side-channel).
    try:
        return hmac.compare_digest(pw.encode("utf-8"), stored.encode("utf-8"))
    except Exception:
        return False


# ── Rate limiting (تسجيل الدخول / لوحة الإدارة) ─────────────
# قبل: /api/login و /api/admin/* بلا أي حد لمحاولات الدخول — brute force مفتوح بالكامل.
_login_attempts: dict = {}


_login_lock          = threading.Lock()


def _login_rate_limited(identifier, max_attempts=8, window=300):
    now = time.time()
    with _login_lock:
        hist = [t for t in _login_attempts.get(identifier, []) if now - t < window]
        hist.append(now)
        _login_attempts[identifier] = hist
        return len(hist) > max_attempts


def _cleanup_login_attempts():
    while True:
        sleep(1800)
        cutoff = time.time() - 1800
        with _login_lock:
            for k in list(_login_attempts.keys()):
                _login_attempts[k] = [t for t in _login_attempts[k] if t > cutoff]
                if not _login_attempts[k]:
                    del _login_attempts[k]


# ── حدود معدل مشتركة بين كل الـ workers (SEC-008 / SEC-014 / SEC-020) ──
# قبل: الحدود فالذاكرة لكل worker (4 workers = الحد ×4)، و addOrder كان محدود بـ ip:phone
# كل 15 ثانية — اللي كان يرفض المنتج الثاني فسلة (طلب لكل منتج).
# دابا: عدّاد بنافذة ثابتة فـ ratelimits/{bucket}/{window}/{hmac(key)} بـ transaction.
# المفتاح مهشّر بسر السيرفر — لا IP ولا اسم مستخدم خام فقاعدة البيانات.
# Firebase طاح → نمرّرو الطلب (fail-open) باش زبائن حقيقيين ما يتحبسوش.
_RATE_LIMITS = {                 # bucket: (حد، النافذة بالثواني)
    "order_ip_store":  (30, 600),    # 30 طلب / 10 دقائق لنفس IP فنفس المتجر (سلة كبيرة عدة مرات)
    "order_store":     (300, 3600),  # 300 طلب / ساعة لكل متجر
    "track_ip":        (20, 600),
    "track_ip_store":  (10, 600),
    "coupon_ip_store": (10, 600),    # تخمين أكواد الخصم
    "coupon_store":    (200, 3600),
    "login_ip":        (20, 600),
    "login_user":      (10, 600),    # password spraying من IPs مختلفة على نفس الحساب
}


_RL_SALT = hashlib.sha256(("ratelimit:" + JWT_SECRET).encode("utf-8")).digest()


def _rl_hash(key):
    return hmac.new(_RL_SALT, str(key).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _shared_limited(bucket, key):
    """True إذا تعدّى الحد (→ 429). كل محاولة تتحسب، حتى المرفوضة."""
    limit, window_s = _RATE_LIMITS[bucket]
    window_id = int(time.time() // window_s)
    seen = {"n": 0}
    def _txn(cur):
        seen["n"] = _safe_int(cur) + 1
        return seen["n"]
    try:
        _firebase_ref(f"ratelimits/{bucket}/{window_id}/{_rl_hash(key)}").transaction(_txn)
    except Exception as e:
        logging.warning(f"shared rate limit unavailable ({type(e).__name__}) — fail-open")
        return False
    return seen["n"] > limit


def _any_shared_limited(*checks):
    """checks = (bucket, key)... بالترتيب (الأضيق أولاً، مثلاً IP ثم المتجر). يوقف عند أول
    حد متعدّى بلا ما يحسب الباقي — باش IP واحد مزعج ما يستهلكش سقف المتجر كامل ويحبس
    الزبائن الحقيقيين."""
    return any(_shared_limited(bucket, key) for bucket, key in checks)


def _cleanup_shared_limits(now=None):
    """يمسح النوافذ القديمة (يخلّي الحالية والسابقة). يتنادى من خيط التنظيف كل ساعة."""
    now = time.time() if now is None else now
    for bucket, (_, window_s) in _RATE_LIMITS.items():
        current = int(now // window_s)
        for w in (_fb_keys(f"ratelimits/{bucket}") or []):
            if _safe_int(w, current) < current - 1:
                _fb_delete(f"ratelimits/{bucket}/{w}")


def _clean_perms(raw):
    raw = raw or {}
    return {k: bool(raw.get(k)) for k in TEAM_PERM_KEYS}


# ── حماية من SSRF فربط متاجر WooCommerce الخارجية ───────────
# قبل: كان يُقبل أي storeUrl يبدأ بـ https:// بلا أي فحص للـ host الفعلي الذي يُحلّ
# إليه، مما يسمح لمستخدم مسجّل بتوجيه سيرفرنا لعمل طلبات HTTP لعناوين داخلية
# (127.0.0.1, 169.254.169.254 metadata endpoint, شبكات خاصة 10.x/172.16.x/192.168.x...)
# عبر DNS يشير لعنوان خاص.
def _resolve_safe_public_ip(hostname):
    """يتحقق من hostname ويرجّع أول IP عام آمن (ليس داخلي/خاص/loopback/link-local/
    reserved/multicast) تم التحقق منه فعلياً، أو None إذا لم يوجد أي IP آمن."""
    if not hostname:
        return None
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return None
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except Exception:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            continue
        return ip_str
    return None


def _validate_and_pin_store_url(store_url):
    """يتحقق من صلاحية رابط المتجر ويرجّع (hostname, safe_ip) للاستعمال المباشر مع
    _request_with_pinned_dns، بدل السماح لـ requests بإعادة حلّ DNS من جديد وقت
    الاتصال (يمنع DNS rebinding). يرجّع (None, None) لو الرابط غير صالح/غير آمن."""
    try:
        parsed = urlparse(store_url)
    except Exception:
        return None, None
    if parsed.scheme != "https" or not parsed.hostname:
        return None, None
    ip = _resolve_safe_public_ip(parsed.hostname)
    if not ip:
        return None, None
    return parsed.hostname, ip


# ── تثبيت DNS (Pinning) بطريقة آمنة على مستوى الـ Thread ────────────
# تحديث مهم (كان الإصدار السابق غير آمن تحت التزامن): النسخة السابقة كانت تُبدّل
# urllib3.util.connection.create_connection على مستوى العملية بأكملها (module-level
# global)، محمية بقفل _dns_pin_lock واحد. المشكلة: هذا القفل يحمي فقط الاستدعاءات
# التي تمر عبر هذه الدالة نفسها (woo/connect وwoo/sync)، بينما بقية الكود يبعث طلبات
# requests أخرى في threads مختلفة بالتوازي (meta_post للفيسبوك/واتساب، تحميل الوسائط،
# Gemini API، keepalive، Facebook OAuth) بلا أي علاقة بهذا القفل. مع ThreadPoolExecutor
# بعدة workers، thread يزامن WooCommerce في نفس اللحظة التي يبعث فيها thread آخر رسالة
# لفيسبوك يقدر يخلي طلب فيسبوك يتوجّه بالخطأ لعنوان WooCommerce المثبَّت (أو العكس) —
# على الأقل فشل اتصال متقطع (TLS handshake سيفشل لعدم مطابقة الشهادة)، وأسوأ الأحوال
# سلوك غير متوقع تحت الحمل. الحل الآن: تثبيت الـ IP يتم فقط على مستوى PoolManager خاص
# بـ HTTPAdapter مُنشأ محلياً لكل طلب (session معزولة)، بلا أي تعديل على أي حالة عالمية
# مشتركة بين threads — كل thread يستعمل adapter خاص به فقط.
class _PinnedHTTPSConnection(HTTPSConnection):
    """اتصال HTTPS يفتح الـ TCP socket فعلياً على IP مثبَّت مسبقاً (self._pinned_ip)
    بدل إعادة حلّ self.host من جديد، مع الحفاظ على SNI/التحقق من الشهادة باسم النطاق
    الأصلي (self.host) — التعديل يطال فقط عنوان الاتصال الأدنى مستوى، ماشي التحقق من TLS."""
    _pinned_ip = None

    def _new_conn(self):
        extra_kw = {}
        if self.source_address:
            extra_kw["source_address"] = self.source_address
        if getattr(self, "socket_options", None):
            extra_kw["socket_options"] = self.socket_options
        target = (self._pinned_ip or self.host, self.port)
        try:
            conn = urllib3.util.connection.create_connection(target, self.timeout, **extra_kw)
        except TypeError:
            conn = urllib3.util.connection.create_connection(target, self.timeout)
        return conn


def _make_pinned_https_adapter(pinned_ip):
    """يبني HTTPAdapter جديد بالكامل (poolmanager خاص به) يفرض الاتصال الفعلي على
    pinned_ip، بلا لمس أي حالة عالمية مشتركة — آمن للاستعمال المتزامن من عدة threads
    فالآن نفسه، كل واحد بـ pinned_ip مختلف."""
    conn_cls = type("_PinnedConn", (_PinnedHTTPSConnection,), {"_pinned_ip": pinned_ip})
    pool_cls = type("_PinnedHTTPSPool", (HTTPSConnectionPool,), {"ConnectionCls": conn_cls})

    class _PinnedAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            self.poolmanager = PoolManager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {"https": pool_cls, "http": urllib3.HTTPConnectionPool}

    return _PinnedAdapter()


def _request_with_pinned_dns(method, url, resolved_ip, **kwargs):
    """يرسل طلب HTTP عبر requests.Session معزولة (محلية لهذا الاستدعاء فقط)، مُلزَمة
    بالاتصال الفعلي بـ resolved_ip الذي تم التحقق منه مسبقاً — يمنع DNS rebinding بلا
    أي تعديل على حالة عالمية مشتركة بين threads."""
    session = requests.Session()
    adapter = _make_pinned_https_adapter(resolved_ip)
    session.mount("https://", adapter)
    try:
        return session.request(method, url, **kwargs)
    finally:
        session.close()
