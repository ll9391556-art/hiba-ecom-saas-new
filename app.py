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
    _reserve_usage,
    _release_usage,
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


# ── /api/saas ─────────────────────────────────────────────
# مسارات محمية تحت data/{uid}/ لا يُسمح بلمسها عبر أفعال firebaseGet/Set/Update/Push
# العامة أدناه — لأن لها منطق تحقق خاص (صلاحيات الخطة، الحدود الشهرية، فحوصات SSRF...)
# ضمن endpoints مخصصة (landing/generate, woo/connect, إلخ).


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

from routes.admin import (
    admin_page,
    api_update_user_plan,
    api_admin_create_client,
    api_admin_rebuild_indexes,
    api_admin_list_clients,
)
from routes.saas import (
    api_saas,
)
import routes.admin as _routes_admin
import routes.saas as _routes_saas
app.register_blueprint(_routes_admin.bp)
app.register_blueprint(_routes_saas.bp)

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