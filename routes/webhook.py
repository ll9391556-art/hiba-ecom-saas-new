# -*- coding: utf-8 -*-
"""webhook ديال Meta (Messenger/Instagram/WhatsApp): تحقق GET وتوقيع POST، ثم المعالجة فـ services/bot.py. منقول من app.py بلا تغيير (Phase 4 / A6)."""
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
    VERIFY_TOKEN,
)
from services.bot import (
    _webhook_object,
    submit_webhook,
    verify_sig,
)

bp = Blueprint("webhook", __name__)




@bp.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # ... كود التحقق (hub.verify_token) يبقى كما هو ...
        if VERIFY_TOKEN and hmac.compare_digest(request.args.get("hub.verify_token") or "", VERIFY_TOKEN):
            return request.args.get("hub.challenge", ""), 200
        return "Forbidden", 403

    # القراءة الخام للبيانات هي أهم خطوة
    raw_body = request.get_data() 
    
    if not verify_sig(raw_body, request.headers):
        # fail-closed: الطلب يترفض وما يتعالجش — object يبيّن أنو منتج (page/instagram/whatsapp) فشل
        logging.error(f"❌ رفض webhook: توقيع غير صالح (403) | object={_webhook_object(raw_body)}")
        return "Forbidden", 403
    
    data = request.get_json(silent=True)
    if not data: return "Bad Request", 400
    logging.info(f"📩 webhook RECEIVED: object={data.get('object')} | entries={len(data.get('entry',[]))}")
    submit_webhook(data)
    return "OK", 200
