# -*- coding: utf-8 -*-
"""بوت المبيعات (Messenger/Instagram/WhatsApp): التحقق من توقيع webhook، معالجة الرسائل فـ
خيوط البوت، Gemini، سجل المحادثة، حفظ الطلبات من البوت، والإرسال عبر Meta API.
منقول من app.py بلا تغيير (Phase 4 / A5) — إلا webhook: المعالجة الداخلية ولّات
handle_webhook_payload، والمسار فـ app.py ينادي submit_webhook. الاختبارات اللي تعوّض
_executor / get_user_settings / process_bg تعوّضهم هنا فـ services.bot."""
import hashlib
import hmac
import json
import logging
import os
import html
import re
import unicodedata
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from time import sleep

import requests
from google import genai
from google.genai import types

from core.config import _GEMINI_MODELS, _JSON_END, _JSON_START, CURRENCY_SYMBOLS_PY, MAX_HISTORY_TURNS, PLANS
from core.db import _fb_get, _fb_keys, _fb_patch, _fb_put, _fb_query, _firebase_ref
from core.security import _cleanup_shared_limits
from core.util import _mask_id
from services.orders import _save_order, _ship_values, _stock_fields, _sold_by_name, _get_stats
from services.users import (_CACHE_TTL, _NEG_CACHE_TTL, _settings_cache, _settings_cache_lock, _under_cap, _increment_usage,
                            _plan_cap, _plan_status, _release_usage, _reserve_usage)

_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="bot_worker")


last_msg_time: dict   = {}


_rate_limit_lock      = threading.Lock()


# منع تكرار تسجيل نفس الطلب من البوت عدة مرات لنفس المحادثة
_recent_bot_orders: dict   = {}


_recent_bot_orders_lock    = threading.Lock()


_DUPLICATE_ORDER_WINDOW    = 1800  # 30 دقيقة


def _is_duplicate_bot_order(uid, sender_id, phone, product):
    # المفتاح بالتاجر + الزبون: نفس رقم واتساب يقدر يطلب من تجار مختلفين
    key = f"{uid}:{sender_id}"
    now = time.time()
    with _recent_bot_orders_lock:
        rec = _recent_bot_orders.get(key)
        if rec and rec.get("phone") == phone and rec.get("product") == product \
                and (now - rec.get("ts", 0)) < _DUPLICATE_ORDER_WINDOW:
            return True
    return False


def _mark_bot_order(uid, sender_id, phone, product):
    with _recent_bot_orders_lock:
        _recent_bot_orders[f"{uid}:{sender_id}"] = {"phone": phone, "product": product, "ts": time.time()}


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
        try:
            _cleanup_shared_limits()
        except Exception as e:
            logging.warning(f"shared rate limit cleanup failed: {type(e).__name__}")


def is_rate_limited(user_id, platform="fb", window=2):
    key = f"{platform}:{user_id}"
    now = time.time()
    with _rate_limit_lock:
        if key in last_msg_time and now - last_msg_time[key] < window:
            return True
        last_msg_time[key] = now
    return False


def _migrate_bot_logs():
    """ينسخ ai_logs/{uid}/{sender}/{push} القديم إلى bot_logs/{uid}/legacy_{sender}_{push}.
    مفاتيح ثابتة → تقدر تعاودها بلا تكرار. القديم ما يتمسحش."""
    uids = _fb_keys("data")
    if uids is None:
        return None
    merchants = copied = 0
    for uid in uids:
        legacy = _fb_get(f"ai_logs/{uid}")
        if not isinstance(legacy, dict):
            continue
        patch = {}
        for sender, rows in legacy.items():
            if not isinstance(rows, dict):
                continue
            for key, row in rows.items():
                if isinstance(row, dict):
                    patch[f"legacy_{sender}_{key}"] = {**row, "sender_id": row.get("sender_id") or sender}
        if patch:
            if not _fb_patch(f"bot_logs/{uid}", patch):
                return None
            merchants += 1
            copied += len(patch)
    return {"merchants": merchants, "copied": copied}


# ── Facebook OAuth ────────────────────────────────────────
def get_user_settings(identifier):
    identifier = str(identifier or "").strip()
    if not identifier: return None
    with _settings_cache_lock:
        cached = _settings_cache.get(identifier)
        ttl = _CACHE_TTL if (cached and cached["data"] is not None) else _NEG_CACHE_TTL
        if cached and time.time() - cached["ts"] < ttl:
            return cached["data"]
    try:
        uname = _fb_get(f"channel_index/{identifier}")
        if uname:
            data = _fb_get(f"users/{uname}")
            if isinstance(data, dict):
                ids = [str(data.get("page_id_FB") or "").strip(),
                       str(data.get("Page_ID_instgram") or "").strip(),
                       str(data.get("page_id_instagram") or "").strip(),
                       str(data.get("phone_number_id") or "").strip()]
                if identifier in ids:
                    with _settings_cache_lock:
                        _settings_cache[identifier] = {"data": data, "ts": time.time()}
                    return data
        # قبل: فهرس ناقص → قراءة /users كاملة فكل webhook لقناة مجهولة. دابا channel_index
        # يتكتب عند حفظ إعدادات البوت (_sync_channel_index) والربط بفيسبوك، والقديم بـ
        # rebuildIndexes. قناة مجهولة: نتذكّروها شوية باش ما نعاودوش نقراو فكل رسالة.
        with _settings_cache_lock:
            _settings_cache[identifier] = {"data": None, "ts": time.time()}
        return None
    except Exception as e:
        logging.error(f"get_user_settings: {e}"); return None


def _bot_allowed_for(bot_settings):
    if not bot_settings: return False
    return PLANS.get(_plan_status(bot_settings)[0], {}).get("bot", False)


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
        logging.error(f"send_facebook_message: NO access_token for recipient {_mask_id(recipient_id)}")
        return False
    if not recipient_id or not text:
        logging.error(f"send_facebook_message: missing recipient_id or text")
        return False
    url = (f"https://graph.facebook.com/v21.0/{page_id}/messages"
           if page_id else "https://graph.facebook.com/v21.0/me/messages")
    logging.info(f"📤 Sending FB message to {_mask_id(recipient_id)} via page {page_id}")
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


# سجل البوت مربوط بالتاجر: chats/{merchant_uid}/{sender_id}. السجل القديم chats/{sender_id}
# (مشترك بين التجار) يبقى فقاعدة البيانات بلا حذف، لكن ما يتقراش.
def get_history(sender_id, merchant_uid):
    if not merchant_uid: return []
    try:
        data = _firebase_ref(f"chats/{merchant_uid}/{sender_id}").get()
        if not data: return []
        hist = sorted(data.values(), key=lambda x: x.get("timestamp",0))
        return hist[-(MAX_HISTORY_TURNS*2):]
    except Exception: return []


def save_history(sender_id, merchant_uid, user_msg, bot_msg):
    if not merchant_uid: return
    try:
        ref = _firebase_ref(f"chats/{merchant_uid}/{sender_id}")
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
    # bot_logs/{uid}/{push} مسطّح (timestamp مفهرس) باش getBotLogs يقرا غير آخر N.
    # قبل: ai_logs/{uid}/{sender}/{push} — ما يتقراش غير كامل. القديم يتنسخ بـ rebuildIndexes.
    try:
        path = f"bot_logs/{merchant_uid}" if merchant_uid else f"ai_logs/{sender_id}"
        _firebase_ref(path).push({
            "user_message":user_msg,"bot_reply":bot_msg,"platform":platform,
            "timestamp":time.time(),"date":time.strftime("%Y-%m-%d %H:%M:%S"),
            "sender_id":sender_id,
        })
    except Exception as e:
        logging.error(f"log_ai_message: {e}")


def _log_conversation(uid, sender_id, direction, text, platform, via="", page_id="", name=""):
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
        # update ينشئ العقدة إذا ما كانتش — بلا قراءة قبل الكتابة فكل رسالة (الواجهة تبيّن
        # senderId إذا الاسم غايب)
        _fb_patch(f"conversations_meta/{uid}/{sender_id}", meta_patch)
    except Exception as e:
        logging.error(f"_log_conversation: {e}")


# عملة ردود البوت = عملة إعدادات المتجر (الافتراضي دج). قبل: الأسعار كانت تدخل للـ prompt
# أرقام بلا عملة، وGemini كان يخمّن ("درهم" مع الدارجة).
_CURRENCY_NAMES = {"DZD": "الدينار الجزائري", "EUR": "اليورو", "USD": "الدولار الأمريكي"}


def _store_currency(uid):
    """(الرمز، الاسم) لعملة المتجر — DZD إذا ما كانتش أو قيمة مجهولة."""
    code = str((_fb_get(f"data/{uid}/storeSettings/currency") if uid else None) or "DZD").upper()
    if code not in CURRENCY_SYMBOLS_PY:
        code = "DZD"
    return CURRENCY_SYMBOLS_PY[code], _CURRENCY_NAMES[code]


def _fmt_price(value):
    """سعر للعرض فردود البوت: بلا ".0" وبفاصل الآلاف (فراغ) — 9500.0 → "9 500".
    الكسور تبان غير إلا كانت (12.5). قيمة ماشي رقم تبقى كيما هي، والفارغة "?"."""
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return "?"
    try:
        num = float(str(value).strip().replace(",", "."))
    except ValueError:
        return str(value).strip()
    if num != num or num in (float("inf"), float("-inf")):
        return str(value).strip()
    rounded = round(num, 2)
    whole = int(abs(rounded))
    frac = ("%.2f" % (abs(rounded) - whole))[1:].rstrip("0").rstrip(".")
    sign = "-" if rounded < 0 else ""
    return sign + f"{whole:,}".replace(",", " ") + frac


# أسماء/فئات المنتجات يكتبوهم التاجر أو أعضاء الفريق (وتجي من WooCommerce): قبل ما يدخلو
# للـ prompt نحيّدو HTML والأسطر الجديدة والحروف الخفية (باش اسم ما يزيدش "تعليمات")، ونحدّو الطول.
_PROMPT_NAME_MAX     = 80
_PROMPT_CATEGORY_MAX = 40
_HTML_TAG = re.compile(r"<[^>]*>")


def _clean_prompt_text(value, max_len):
    if value is None:
        return ""
    s = _HTML_TAG.sub(" ", str(value))
    s = _HTML_TAG.sub(" ", html.unescape(s))
    s = "".join(" " if unicodedata.category(ch) in ("Cc", "Zl", "Zp") else ch
                for ch in s if unicodedata.category(ch) != "Cf")
    s = " ".join(s.split())
    return s if len(s) <= max_len else s[:max_len - 1].rstrip() + "…"


def get_products_text(bot_settings, currency=None):
    try:
        uid      = bot_settings.get("User_ID")
        products = _fb_get(f"data/{uid}/products") if uid else None
        if products and isinstance(products, dict):
            symbol = (currency or _store_currency(uid))[0]
            sold = _sold_by_name(_get_stats(uid))
            lines = [f"- {_clean_prompt_text(p.get('name','?'), _PROMPT_NAME_MAX)}: {_fmt_price(p.get('sell'))} {symbol} | stock:{_stock_fields(p, sold.get(p.get('name',''), 0))['available']} | {_clean_prompt_text(p.get('category',''), _PROMPT_CATEGORY_MAX)}".strip()
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

        if sender_id and _is_duplicate_bot_order(uid, sender_id, phone, product):
            logging.info(f"⏭️ تجاهل طلب مكرر من البوت | sender={_mask_id(sender_id)} | product={product}")
            return False

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
        _save_order(uid, order_id, order)
        _increment_usage(uid, "orderCount")
        if sender_id: _mark_bot_order(uid, sender_id, phone, product)
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
    merchant_uid = str(bot_settings.get("User_ID","") or "")
    try:
        instructions = bot_settings.get("AI_instructions","أنت مساعد مبيعات ذكي.")
        currency     = _store_currency(merchant_uid)
        products     = get_products_text(bot_settings, currency)
        history_text = history_to_text(get_history(sender_id, merchant_uid))
        req_format = '{"product":"اسم المنتج","quantity":"الكمية","name":"اسم العميل","phone":"رقم الهاتف","city":"المدينة","delivery_type":"منزل أو مكتب الاستلام","address":"العنوان"}'
        system_text = f"""أنت مساعد مبيعات لمتجر إلكتروني. مهمتك مساعدة العملاء في الطلب.
رد بنفس لغة العميل (عربي أو فرنسي).
العملة: {currency[0]} ({currency[1]}). اكتب كل الأسعار بهذه العملة وبهذا الشكل: 9 500 {currency[0]}. لا تستعمل درهم ولا أي عملة أخرى.
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
            logging.info(f"📦 JSON extracted for {_mask_id(sender_id)}: fields={list(order_data.keys())}")
            is_valid, reason = validate_order(order_data)
            if not is_valid:
                logging.warning(f"⚠️ Order invalid for {_mask_id(sender_id)}: {reason}")
                try:
                    retry_text, _ = _gemini_generate_with_fallback(api_key,
                        [types.Part.from_text(text=f'العميل: "{user_message}"\nالناقص: {reason}\nاسأل بلطف.')],
                        types.GenerateContentConfig(temperature=0.5,max_output_tokens=512),"retry")
                    clean_text = retry_text
                except Exception: pass
                order_data = None
        save_history(sender_id, merchant_uid, user_message, clean_text)
        log_ai_message(sender_id, user_message, clean_text, merchant_uid=merchant_uid)
        return clean_text, order_data
    except Exception as e:
        logging.error(f"ask_gemini {_mask_id(sender_id)}: {e}")
        return _GEMINI_ERROR_REPLY, None


_GEMINI_ERROR_REPLY = "عذراً، حاول مرة أخرى بعد قليل."

# ماسنجر وإنستغرام ما يعرضوش Markdown: Gemini يكتب **غليظ** و*مائل* و## عناوين و`كود`
# والزبون يشوف النجوم كما هي. نحيّدو الرموز بلا ما نبدّلو الكلام (واتساب يعرض *غليظ*، يبقى).
_MD_HEADING = re.compile(r"^(\s*)#{1,6}\s+", re.M)
_MD_BULLET  = re.compile(r"^(\s*)\*\s+", re.M)
_MD_BOLD    = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_ITALIC  = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_PLAIN_TEXT_PLATFORMS = ("fb", "ig")


def _strip_markdown(text):
    if not text:
        return text
    s = _MD_HEADING.sub(r"\1", text)
    s = _MD_BULLET.sub(r"\1• ", s)
    s = _MD_BOLD.sub(r"\1", s)
    s = _MD_ITALIC.sub(r"\1", s)
    return s.replace("`", "").replace("*", "")


def process_bg(sender_id, user_text, bot, send_fn,
               media_bytes=b"", mime_type="", is_voice=False, is_image=False, platform="fb", page_id=""):
    def task():
        logging.info(f"🔄 process_bg START | sender={_mask_id(sender_id)} | platform={platform} | text_len={len(user_text or '')}")
        reserved = False
        try:
            merchant_uid = bot.get("User_ID", "")
            # سقف ردود البوت الشهري (PLANS[plan]["botMsgCap"]): حجز ذرّي قبل Gemini. عند الحد
            # البوت يسكت — حتى رسالة للزبون — والرسالة الواردة راهي مسجّلة فالمحادثات من قبل،
            # والتاجر يشوف التنبيه فاللوحة ويجاوب يدوياً.
            if merchant_uid:
                if not _reserve_usage(merchant_uid, "botMsgCount", _plan_cap(merchant_uid, "botMsgCap")):
                    logging.warning(f"⏭️ سقف ردود البوت الشهري | uid={merchant_uid} — بلا Gemini وبلا رد")
                    return
                reserved = True
            reply, order = ask_gemini(sender_id,user_text,bot,
                                      media_bytes=media_bytes,mime_type=mime_type,
                                      is_voice=is_voice,is_image=is_image)
            if reply == _GEMINI_ERROR_REPLY and not order:
                _release_usage(merchant_uid, "botMsgCount"); reserved = False
            logging.info(f"🤖 ask_gemini DONE | sender={_mask_id(sender_id)} | reply_len={len(reply or '')} | order={'yes' if order else 'no'}")
            if order and (not reply or not reply.strip()):
                reply = "✅ تم استلام طلبك بنجاح! سنتواصل معك قريباً لتأكيد التوصيل."
            elif not reply or not reply.strip():
                reply = "عذراً، لم أتمكن من المعالجة الآن. حاول مرة أخرى."
            if platform in _PLAIN_TEXT_PLATFORMS:
                reply = _strip_markdown(reply)  # نفس النص يتبعث ويتسجّل فالمحادثات
            try:
                ok = send_fn(reply)
                logging.info(f"📨 send_fn result for {_mask_id(sender_id)}: {ok}")
                if ok and merchant_uid:
                    _log_conversation(merchant_uid, sender_id, "out", reply, platform, via="bot", page_id=page_id)
            except Exception as send_err:
                logging.error(f"send_fn raised exception ({_mask_id(sender_id)}): {send_err}")
            reserved = False  # Gemini جاوب: الوحدة مستهلكة حتى لو فشل شي حاجة من بعد
            if order:
                save_order_from_bot(order, bot, sender_id)
        except Exception as e:
            logging.error(f"BG task ({_mask_id(sender_id)}): {e}", exc_info=True)
            if reserved:
                _release_usage(merchant_uid, "botMsgCount")
            try: send_fn("عذراً، حدث خطأ مؤقت.")
            except Exception: pass
    _executor.submit(task)


def _webhook_object(raw_body):
    """للسجلات فقط: نوع المنتج اللي بعث الـ webhook (بلا أي محتوى آخر من الجسم)."""
    try:
        obj = json.loads(raw_body).get("object")
    except Exception:
        return "?"
    return obj if obj in ("page", "instagram", "whatsapp_business_account") else "?"


def verify_sig(raw_body, headers):
    # 1. جلب الأسرار: سر تطبيق ميتا (فيسبوك/واتساب/إنستغرام عبر Facebook Login)
    #    + سر إنستغرام المنفصل (Instagram API with Instagram Login يوقّع بيه وحدو)
    keys = []
    for name in ("META_APP_SECRET", "INSTAGRAM_APP_SECRET"):
        k = os.environ.get(name, "").strip()
        if k and k not in keys:
            keys.append(k)
    if not keys:
        logging.critical("🚨 META_APP_SECRET مفقود من متغيرات البيئة!")
        return False
    
    # 2. جلب التوقيع من الهيدر
    sig_header = headers.get("X-Hub-Signature-256", "")
    if not sig_header.startswith("sha256="):
        logging.warning("⚠️ لم يتم العثور على sha256 في الهيدر")
        return False
    
    received_sig = sig_header[7:]

    # 3+4. حساب التوقيع على البيانات الخام لكل سر + مقارنة زمن-ثابت
    #      — بلا تسجيل أي جزء من التوقيعات أو السر أو جسم الطلب
    match = False
    for k in keys:
        calculated_sig = hmac.new(k.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(calculated_sig, received_sig):
            match = True

    if not match:
        logging.warning(f"⚠️ توقيع webhook غير مطابق | حجم البيانات: {len(raw_body)} بايت")

    return match


_STICKERS   = ["😊 أهلاً! كيف يمكنني مساعدتك؟","👋 مرحباً! يسعدنا خدمتك.","❤️ شكراً لتواصلك!"]


_sticker_i  = 0


_sticker_lk = threading.Lock()


def sticker_reply():
    global _sticker_i
    with _sticker_lk:
        r = _STICKERS[_sticker_i % len(_STICKERS)]; _sticker_i += 1
    return r


def handle_webhook_payload(payload):
    """معالجة رسائل webhook (فيسبوك/إنستغرام/واتساب) فـ خيط البوت — كانت دالة داخلية فـ webhook()."""
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
                        if is_rate_limited(f"{merchant_uid_wa}:{sid}","wa"): continue
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
                send_pid = (fb_pid or None) if is_instagram else page_id
                logging.info(f"🔑 Using {'Instagram' if is_instagram else 'Facebook'} token for page_id={page_id} | send_pid={send_pid or 'me'}")
                platform_str = "ig" if is_instagram else "fb"
                merchant_uid_fb = bot.get("User_ID", "")
                msging_list = entry.get("messaging",[]) or []
                logging.info(f"📋 messaging entries count: {len(msging_list)}")
                for me in msging_list:
                    sid=me.get("sender",{}).get("id","")
                    logging.info(f"👤 processing message from sid={_mask_id(sid)}")
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
                        logging.info(f"⏭️ skipped: no text/media extracted from message")
                        continue
                    log_text_fb = utxt or ("🎙️ [رسالة صوتية]" if isvoc else "🖼️ [صورة]" if isimg else "")
                    if merchant_uid_fb:
                        _log_conversation(merchant_uid_fb, sid, "in", log_text_fb, platform_str, page_id=(send_pid or page_id))
                    if is_rate_limited(f"{merchant_uid_fb}:{sid}","fb"):
                        logging.info(f"⏭️ skipped: rate limited for sid={_mask_id(sid)}")
                        continue
                    def fb_fn(reply,_sid=sid,_tok=tok,_pid=send_pid): return send_facebook_message(_sid,reply,_tok,page_id=_pid)
                    process_bg(sid,utxt,bot,fb_fn,mdata,mime,isvoc,isimg,platform_str,(send_pid or page_id))
    except Exception as e:
        logging.error(f"handle() error: {e}")


def submit_webhook(payload):
    _executor.submit(handle_webhook_payload, payload)
