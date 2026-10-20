# -*- coding: utf-8 -*-
"""ربط فيسبوك/إنستغرام (OAuth): state مربوط بالمتصفح بـ nonce، صفحات النافذة المنبثقة، حالة الربط. منقول من app.py بلا تغيير (Phase 4 / A6)."""
import hashlib
import hmac
import json
import logging
import re
import secrets

import jwt
import time
from urllib.parse import quote, unquote

import requests
from flask import Blueprint, abort, jsonify, make_response, request, send_from_directory
from markupsafe import escape as _esc

from core.config import (
    FB_APP_ID,
    FB_APP_SECRET_OAUTH,
    JWT_ALGO,
    JWT_SECRET,
    REDIRECT_URI,
    _ALLOWED_ORIGINS,
)
from core.db import (
    _fb_get,
    _fb_patch,
    _fb_put,
    _firebase_ref,
)
from core.http import (
    ok_json,
)
from core.security import (
    decode_token,
    require_auth,
    require_owner,
)

from core.templates import render
from markupsafe import Markup
bp = Blueprint("oauth", __name__)




# رسالة ثابتة لكل أخطاء الربط — نص الاستثناء (فيه URL كامل بـ client_secret/access_token)
# ما يتعرضش للمستخدم ولا يتسجّل أبداً.
_OAUTH_FAIL_MSG = "تعذّر إكمال الربط مع فيسبوك — حاول مرة أخرى"


_OAUTH_STATE_BAD_MSG = "انتهت صلاحية طلب الربط أو أنه غير صالح — أعد المحاولة من لوحة التحكم"


# ── ربط state بالمتصفح (SEC-004) ──
# getOAuthState يولّد nonce عشوائي: يتحط فكوكي HttpOnly، والـ hash ديالو فالـ state
# وفـ oauth_pending/{uid} (خانة وحدة لكل تاجر). /callback يقبل غير إلا الكوكي مطابقة
# والخانة موجودة، ويمسحها (استعمال واحد). هكا state مسروق أو مبعوث لضحية ما يخدمش
# فمتصفح آخر.
_OAUTH_COOKIE    = "of_oauth_nonce"


_OAUTH_STATE_TTL = 600


def _nonce_hash(nonce):
    return hashlib.sha256(str(nonce).encode("utf-8")).hexdigest()


class _NonceRejected(Exception):
    pass


def _consume_oauth_nonce(uid, nh):
    """يستهلك oauth_pending/{uid} ذرّياً إذا كان مطابق وما انتهاش — يرجّع True مرة وحدة فقط.
    firebase-admin يرفض None فالـ transaction (ما يمسحش)، لذلك نكتبو علامة "مستعمل" بلا nh،
    ومحاولة ربط جديدة تكتب فوقها. عند عدم التطابق نوقفو الـ transaction بلا ما نكتبو."""
    def _txn(cur):
        if (isinstance(cur, dict) and int(cur.get("exp", 0) or 0) > time.time()
                and hmac.compare_digest(str(cur.get("nh", "")).encode(), nh.encode())):
            return {"used": int(time.time())}
        raise _NonceRejected()
    try:
        _firebase_ref(f"oauth_pending/{uid}").transaction(_txn)
        return True
    except _NonceRejected:
        return False
    except Exception as e:
        logging.error(f"OAuth nonce consume failed: {type(e).__name__}")
        return False


@bp.route("/callback", methods=["GET"])
def fb_oauth_callback():
    resp = make_response(_fb_oauth_callback_page())
    # الكوكي ما تبقاش بعد أي محاولة (نجاح ولا فشل)
    resp.delete_cookie(_OAUTH_COOKIE, path="/callback", secure=True, httponly=True, samesite="Lax")
    return resp


def _fb_oauth_callback_page():
    code  = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error: return _oauth_error_page("تم إلغاء الربط أو رفضه من فيسبوك")
    if not code or not state: return _oauth_error_page("Missing code or state")
    # التحقق من state + كوكي المتصفح قبل أي نداء لفيسبوك — توكن جلسة (أو أي نوع آخر) ما يتقبلش هنا
    sd    = decode_token(unquote(state), typ="oauth_state") or {}
    uid   = str(sd.get("uid","") or "").strip()
    uname = str(sd.get("uname","") or "").strip()
    if not uid:
        logging.error("OAuth state verification failed")
        return _oauth_error_page(_OAUTH_FAIL_MSG)
    nh = str(sd.get("nh", "") or "")
    cookie_nonce = request.cookies.get(_OAUTH_COOKIE, "")
    if not (nh and cookie_nonce and hmac.compare_digest(_nonce_hash(cookie_nonce).encode(), nh.encode())
            and _consume_oauth_nonce(uid, nh)):
        logging.warning("OAuth state rejected: browser nonce missing, mismatched or already used")
        return _oauth_error_page(_OAUTH_STATE_BAD_MSG)
    try:
        r1 = requests.get("https://graph.facebook.com/v19.0/oauth/access_token",
            params={"client_id":FB_APP_ID,"client_secret":FB_APP_SECRET_OAUTH,
                    "redirect_uri":REDIRECT_URI,"code":code}, timeout=15)
        if not r1.ok:
            logging.error(f"OAuth code exchange failed: HTTP {r1.status_code}")
            return _oauth_error_page(_OAUTH_FAIL_MSG)
        short_token = r1.json().get("access_token")
        if not short_token: raise ValueError("No access_token")
        r2 = requests.get("https://graph.facebook.com/v19.0/oauth/access_token",
            params={"grant_type":"fb_exchange_token","client_id":FB_APP_ID,
                    "client_secret":FB_APP_SECRET_OAUTH,"fb_exchange_token":short_token}, timeout=15)
        if not r2.ok:
            logging.error(f"OAuth long-lived token exchange failed: HTTP {r2.status_code}")
            return _oauth_error_page(_OAUTH_FAIL_MSG)
        long_token = r2.json().get("access_token", short_token)
        r3 = requests.get("https://graph.facebook.com/v19.0/me/accounts",
            params={"access_token":long_token,"fields":"id,name,access_token,instagram_business_account"},
            timeout=15)
        if not r3.ok:
            logging.error(f"OAuth /me/accounts failed: HTTP {r3.status_code}")
            return _oauth_error_page(_OAUTH_FAIL_MSG)
        pages = r3.json().get("data",[]) or []
        logging.info(f"📘 FB /me/accounts pages received: {len(pages)}")
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
            try:
                if fb_page_id: _fb_put(f"channel_index/{fb_page_id}", uname)
                if ig_page_id: _fb_put(f"channel_index/{ig_page_id}", uname)
            except Exception as e:
                logging.error(f"channel_index update failed: {e}")
        logging.info(f"✅ OAuth OK UID={uid}")
        ph = "".join(f"<div style='display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px'>"
                     f"<span>{'📷' if p['type']=='instagram' else '📘'}</span>"
                     f"<span>{_esc(p.get('name','—'))}</span></div>" for p in pages_info)
        return render("oauth_success.html",
            pages_box=Markup('<div style="margin-top:16px;background:rgba(255,255,255,.04);border-radius:10px;padding:12px">' + ph + '</div>' if ph else ''),
            opener_js=Markup(_post_to_opener_js('{type:"FB_AUTH_SUCCESS"}')),
        )
    except Exception as err:
        logging.error(f"OAuth error: {type(err).__name__}"); return _oauth_error_page(_OAUTH_FAIL_MSG)


def _js_str(v):
    """نص JSON آمن داخل <script> — json.dumps وحده ما يهرّبش </script>."""
    return json.dumps(str(v)).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _post_to_opener_js(msg_js):
    """postMessage لكل origin فـ ALLOWED_ORIGINS (أبداً "*"). المتصفح يتجاهل بصمت الـ origin
    اللي ما يطابقش النافذة الأم، والرسالة ما فيها حتى توكن — الواجهة تعاود تجيب من السيرفر."""
    targets = ",".join(_js_str(o) for o in _ALLOWED_ORIGINS)
    return (f"[{targets}].forEach(function(o){{try{{window.opener&&"
            f"window.opener.postMessage({msg_js},o);}}catch(e){{}}}});")


def _oauth_error_page(msg):
    return render("oauth_error.html",
        msg=msg,
        opener_js=Markup(_post_to_opener_js('{type:"FB_AUTH_ERROR",message:' + _js_str(msg) + '}')),
    )


@bp.route("/api/getOAuthState", methods=["GET"])
@require_auth
@require_owner
def api_get_oauth_state():
    nonce = secrets.token_urlsafe(32)
    nh    = _nonce_hash(nonce)
    exp   = int(time.time()) + _OAUTH_STATE_TTL
    # خانة وحدة لكل تاجر: محاولة ربط جديدة تلغي القديمة
    _fb_put(f"oauth_pending/{request.auth_uid}", {"nh": nh, "exp": exp})
    state = jwt.encode({
        "uid": request.auth_uid, "uname": request.auth_username, "typ": "oauth_state",
        "nh": nh, "exp": exp,
    }, JWT_SECRET, algorithm=JWT_ALGO)
    resp = ok_json({"state": state})
    resp.set_cookie(_OAUTH_COOKIE, nonce, max_age=_OAUTH_STATE_TTL, path="/callback",
                    secure=True, httponly=True, samesite="Lax")
    return resp


@bp.route("/fb-status", methods=["GET"])
@require_auth
@require_owner
def fb_status():
    uid  = request.auth_uid
    data = _fb_get(f"data/{uid}/fbTokens")
    if data and isinstance(data,dict) and data.get("connected"):
        return jsonify({"connected":True,"updated_at":data.get("updated_at","—"),"pages":data.get("pages",[])})
    return jsonify({"connected":False})


@bp.route("/fb-disconnect", methods=["POST"])
@require_auth
@require_owner
def fb_disconnect():
    uid = request.auth_uid
    _fb_patch(f"data/{uid}/fbTokens", {"connected":False,"fb_access_token":"",
        "instgram_access_token":"","pages":[],"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S")})
    return jsonify({"status":"ok"})
