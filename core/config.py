# -*- coding: utf-8 -*-
"""الإعدادات: متغيرات البيئة، الأسرار (مع رفض الإقلاع فالإنتاج بلا أسرار)، الثوابت والخطط.
منقول من app.py بلا تغيير (Phase 4 / A3). app.py يعاود يصدّر نفس الأسماء.
ملاحظة: logging.basicConfig هنا لأن هاد الملف هو أول واحد يكتب فالسجل وقت الإقلاع."""
import logging
import os
import secrets

from cryptography.fernet import Fernet

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", force=True)

_TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "https://orderconfidence.com"
).split(",") if o.strip()]

MAX_PAYLOAD_SIZE       = 2 * 1024 * 1024
# حد Flask العام (MAX_CONTENT_LENGTH): يشمل حتى الطلبات بلا Content-Length (chunked).
# الرفع وحدو يفوت 2MB: صورة منتج حتى 5MB، شعار حتى 1MB (الحدود فـ routes/store.py).
MAX_CONTENT_LENGTH     = 6 * 1024 * 1024
UPLOAD_PATHS           = ("/api/uploadImage", "/api/uploadStoreLogo")
MAX_HISTORY_TURNS      = 10
LOW_STOCK_THRESHOLD    = 5
BAD_CUSTOMER_THRESHOLD = 3
_JSON_START            = "###JSON_START###"
_JSON_END              = "###JSON_END###"

_GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

# ── Meta webhook verify token ──────────────────────────────
# قبل: قيمة افتراضية ثابتة بالكود ("HEBA_SAAS_2026") معروفة لأي شخص يقرأ المصدر.
# الآن: إجباري من البيئة، بلا قيمة افتراضية.
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "").strip()
if not VERIFY_TOKEN:
    logging.critical("🚨 VERIFY_TOKEN غير مضبوط بالبيئة — أي محاولة تحقق GET من ميتا على /webhook سترفض حتى تضبطه.")

META_APP_SECRET = (os.environ.get("META_APP_SECRET") or os.environ.get("FB_APP_SECRET") or "").strip()
if not META_APP_SECRET:
    logging.critical("🚨 META_APP_SECRET غير مضبوط — /webhook سيرفض كل الطلبات POST حتى يُضبط (fail-closed).")
FB_DB_URL           = os.environ.get("FB_DB_URL",    "https://saas-order-default-rtdb.europe-west1.firebasedatabase.app").strip()
FB_APP_ID           = os.environ.get("FB_APP_ID",    "1484940433173462").strip()
FB_APP_SECRET_OAUTH = os.environ.get("FB_APP_SECRET","").strip()
REDIRECT_URI        = os.environ.get("REDIRECT_URI", "https://orderconfidence.com/callback").strip()
FB_STORAGE_BUCKET   = os.environ.get("FB_STORAGE_BUCKET", "saas-order.firebasestorage.app").strip()

# ── Auth (JWT) ────────────────────────────────────────────
# قبل: عند غياب JWT_SECRET كان يُستعمل نص ثابت مكتوب بالكود
# ("INSECURE_DEV_SECRET_CHANGE_ME_NOW") — أي شخص يقرأ هذا الملف يقدر يزوّر
# جلسة owner كاملة لأي حساب. الآن: سر عشوائي قوي يُولَّد وقت التشغيل بدل قيمة معروفة.
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(32)
    logging.critical("🚨 JWT_SECRET غير مضبوط بالبيئة — تم توليد سر عشوائي مؤقت لهذه الجلسة فقط "
                      "(كل التوكنات الحالية ستُبطَل عند إعادة التشغيل القادمة). "
                      "اضبط JWT_SECRET بقيمة ثابتة بالإنتاج فوراً!")
JWT_ALGO         = "HS256"
# صلاحية الجلسة: تختلف حسب الدور — عضو الفريق 24 ساعة (نافذة أضيق لو تاجر
# طرد موظف)، صاحب الحساب 7 أيام (بلا حاجة يعاود الدخول يوميًا لحسابه الخاص).
# ملاحظة: بفضل التحقق الحي من team_users فـ require_auth، حتى لو التوكن ماشي
# منتهي، عضو معطّل/محذوف يُرفض فورًا بلا انتظار — هاذي المدة طبقة دفاع إضافية فقط.
JWT_EXPIRY_HOURS_OWNER  = 24 * 7   # 7 أيام
JWT_EXPIRY_HOURS_MEMBER = 24       # 24 ساعة

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "").strip()
if not ADMIN_API_KEY:
    logging.warning("⚠️ ADMIN_API_KEY غير مضبوط — مسارات الإدارة (تغيير الخطط) سترفض كل الطلبات حتى يُضبط.")

# ── تشفير مفاتيح API لمتاجر العملاء الخارجية (WooCommerce/Shopify) ─────
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "").strip()
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    logging.warning("⚠️ ENCRYPTION_KEY غير مضبوط — تم توليد مفتاح مؤقت (سيُفقد عند إعادة التشغيل، "
                     "وستنقطع كل الاتصالات الخارجية المحفوظة). اضبط ENCRYPTION_KEY ثابت فالإنتاج فوراً.")
try:
    _fernet = Fernet(ENCRYPTION_KEY.encode())
except Exception as e:
    logging.error(f"ENCRYPTION_KEY غير صالح: {type(e).__name__} — تم توليد مفتاح بديل مؤقت")
    _fernet = Fernet(Fernet.generate_key())

# ── رفض الإقلاع فالإنتاج بلا أسرار ثابتة (ARC-001) ──
# المفاتيح المؤقتة فوق مقبولة غير فالتطوير: فالإنتاج كل worker كان يولّد سر مختلف →
# توكنات ترفض عشوائياً وبيانات الربط المشفّرة تولّي غير مقروءة. Render يضبط RENDER=true.
_IS_PRODUCTION = (os.environ.get("RENDER", "").strip().lower() == "true"
                  or os.environ.get("APP_ENV", "").strip().lower() == "production")
_boot_problems = []
if not os.environ.get("JWT_SECRET", "").strip():
    _boot_problems.append("JWT_SECRET missing")
_enc_env = os.environ.get("ENCRYPTION_KEY", "").strip()
if not _enc_env:
    _boot_problems.append("ENCRYPTION_KEY missing")
else:
    try:
        Fernet(_enc_env.encode())
    except Exception:
        _boot_problems.append("ENCRYPTION_KEY invalid (must be a Fernet key: 44 chars, base64)")
if _IS_PRODUCTION and _boot_problems:
    raise RuntimeError("Refusing to start in production: " + "; ".join(_boot_problems))

# الباقات (design/PLAN.md — المهمة 1). الدفع يدوي (BaridiMob/CCP) والأدمين يفعّل الباقة.
# price بالدينار: monthly/yearly. integrations = WooCommerce. templates = عدد قوالب المتجر.
# الميزات: dashboard/orders (مع المنتجات والولايات) للكل؛ store متجر عام؛ tracking تتبع الطلب؛
# export تصدير الطلبات؛ coupons؛ landing صفحات هبوط؛ bot + botMsgCap ردود/شهر؛ team؛ vip دعم.
_FREE_FEATURES = {"dashboard": True, "orders": True, "store": False, "tracking": False, "export": False,
                  "templates": 0, "bot": False, "landing": False, "integrations": False, "coupons": False,
                  "team": False, "vip": False}
_STARTER_FEATURES = {**_FREE_FEATURES, "store": True, "tracking": True, "export": True, "templates": 2}
_PRO_FEATURES = {**_STARTER_FEATURES, "bot": True, "botMsgCap": 1500, "landing": True, "integrations": True,
                 "coupons": True, "templates": "all"}
_BUSINESS_FEATURES = {**_PRO_FEATURES, "botMsgCap": 5000, "team": True, "vip": True}

PLANS = {
    "free":       {**_FREE_FEATURES,     "label": "Free",     "price": {"monthly": 0}},
    "starter":    {**_STARTER_FEATURES,  "label": "Starter",  "price": {"monthly": 1500}},
    "pro":        {**_PRO_FEATURES,      "label": "Pro",      "price": {"monthly": 2900, "yearly": 24900}},
    "business":   {**_BUSINESS_FEATURES, "label": "Business", "price": {"monthly": 4900}},
    # أوائل التجار: Pro كاملة بسعر سنوي، لأول EARLY_MAX_SLOTS تاجر، تفعيل يدوي من الأدمين
    "early":      {**_PRO_FEATURES,      "label": "Early",    "price": {"yearly": 19900}},
    # ── باقات قديمة: يبقاو يخدمو للمشتركين الحاليين ──
    "full":       {"bot": True,  "store": True,  "landing": True,  "dashboard": True, "orders": True, "integrations": True,  "team": True,  "label": "Full",
                    "orderCap": 300, "botMsgCap": 3000},
    "lifetime":   {"bot": True,  "store": True,  "landing": True,  "dashboard": True, "orders": True, "integrations": True,  "team": True,  "label": "Lifetime",
                    "orderCap": 300, "botMsgCap": 3000},
    "bot_only":   {"bot": True, "store": False, "landing": False, "dashboard": False,
                    "orders": False, "integrations": False, "team": False, "label": "Bot Only"},
}

# أسماء قديمة → الباقة الحالية. enterprise ولّات business: تتقرا business فكل مكان،
# وrebuildIndexes يبدّل القيمة المخزّنة مرة وحدة.
PLAN_ALIASES = {"enterprise": "business"}


def normalize_plan(plan, default="starter"):
    """قيمة plan الخام (من users/{u}) → مفتاح فـ PLANS. غياب الحقل = starter، كيما قبل."""
    plan = str(plan if plan not in (None, "") else default).strip().lower()
    return PLAN_ALIASES.get(plan, plan)


CURRENCY_SYMBOLS_PY = {"DZD": "دج", "EUR": "€", "USD": "$"}

# لون المتجر العام (D4a): storeSettings.color = المفتاح، (أساسي، فاتح). المتجر وصفحة التتبع برك؛
# اللوحة تبقى بألوان OrderFlow. نفس الجدول فـ static/js/shop.js (SHOP_COLORS). بلا color = violet.
STORE_COLORS = {
    "violet":  ("#3B2BFF", "#E6E3FF"),
    "blue":    ("#1D4ED8", "#DBEAFE"),
    "emerald": ("#0F766E", "#CCFBF1"),
    "orange":  ("#C2410C", "#FFEDD5"),
    "pink":    ("#BE123C", "#FFE4E6"),
    "mauve":   ("#7C3AED", "#EDE9FE"),
}
DEFAULT_STORE_COLOR = "violet"

BOT_LAUNCHED = os.environ.get("BOT_LAUNCHED", "true").strip().lower() == "true"

# ── فريق العمل (Team Members) ──────────────────────────────
MAX_TEAM_MEMBERS = 6
TEAM_PERM_KEYS = ["orders", "products", "customers", "cities", "store", "bot", "messages", "integrations", "landing"]

LIFETIME_MAX_SLOTS = 50
EARLY_MAX_SLOTS = 50  # عرض أوائل التجار — counters/earlyAccounts
