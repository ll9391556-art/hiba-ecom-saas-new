# -*- coding: utf-8 -*-
"""SEC-007 — ما يتسجّلش أي جزء من الأسرار ولا بيانات الزبون الشخصية."""
import hashlib
import hmac
import json
import logging
import os
import pathlib
import subprocess
import sys

import pytest

from tests import fakes

ROOT = pathlib.Path(__file__).resolve().parent.parent

SENDER = "213555987654"            # رقم واتساب الزبون = sender_id
PHONE = "0555123456"
ADDRESS = "12 Rue Secrete"
ORDER = {"product": "Sac", "quantity": "1", "name": "Amina Testname", "phone": PHONE,
         "city": "Alger", "delivery_type": "منزل", "address": ADDRESS}
PII = (SENDER, PHONE, ADDRESS, "Amina Testname")


def _assert_no_pii(text):
    for needle in PII:
        assert needle not in text, f"{needle!r} found in logs"


def test_import_does_not_log_meta_secret_parts():
    secret = "QZ7Xk-dummy-tail-W9pL"
    code = (
        "import os, socket, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from tests import fakes\n"
        "def _b(*a, **k): raise fakes.NetworkBlocked('blocked')\n"
        "socket.create_connection = _b; socket.socket.connect = _b; socket.getaddrinfo = _b\n"
        "fakes.install()\n"
        "import app\n"
    )
    env = {**os.environ, "META_APP_SECRET": secret, "FB_APP_SECRET": secret,
           "JWT_SECRET": "dummy-jwt", "ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
           "VERIFY_TOKEN": "dummy-verify", "PYTHONIOENCODING": "utf-8"}
    env.pop("FIREBASE_CREDENTIALS", None)
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert "FIREBASE_CREDENTIALS missing" in proc.stderr  # الالتقاط يخدم فعلاً
    assert secret[:5] not in proc.stderr
    assert secret[-5:] not in proc.stderr


def test_verify_sig_failure_logs_no_signature_material(app, caplog):
    caplog.set_level(logging.INFO)
    body = b'{"object":"page","entry":[]}'
    key = os.environ["META_APP_SECRET"].encode()
    assert app.verify_sig(body, {"X-Hub-Signature-256": "sha256=" + "0" * 64}) is False
    test_hash = hmac.new(key, b"test", hashlib.sha256).hexdigest()[:10]
    calculated = hmac.new(key, body, hashlib.sha256).hexdigest()[:10]
    assert test_hash not in caplog.text
    assert calculated not in caplog.text
    assert '"object"' not in caplog.text


def test_verify_sig_still_accepts_valid_signature(app):
    body = b'{"object":"page"}'
    sig = hmac.new(os.environ["META_APP_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    assert app.verify_sig(body, {"X-Hub-Signature-256": "sha256=" + sig}) is True


@pytest.fixture
def gemini_order_reply():
    fakes.GEMINI_RESPONDER["fn"] = lambda model, contents, config: (
        "تم تسجيل طلبك ✅\n###JSON_START###" + json.dumps(ORDER, ensure_ascii=False) + "###JSON_END###")


def test_ask_gemini_does_not_log_order_pii(app, caplog, gemini_order_reply):
    caplog.set_level(logging.INFO)
    reply, order = app.ask_gemini(SENDER, "نحب نطلب", {"Gemini_api_key": "dummy-gemini-key",
                                                       "User_ID": "1001"})
    assert order and order["phone"] == PHONE  # السلوك نفسه ما تبدّلش
    _assert_no_pii(caplog.text)


def test_process_bg_does_not_log_message_text_or_sender(app, caplog, monkeypatch, seed_owner,
                                                         gemini_order_reply):
    caplog.set_level(logging.INFO)
    owner = seed_owner()

    class SyncExecutor:
        def submit(self, fn, *a, **kw):
            fn(*a, **kw)

    monkeypatch.setattr("services.bot._executor", SyncExecutor())
    sent = []
    bot = {"Gemini_api_key": "dummy-gemini-key", "User_ID": owner["uid"], "plan": "pro"}
    app.process_bg(SENDER, f"رقمي {PHONE} وعنواني {ADDRESS}", bot,
                   lambda reply: sent.append(reply) or True, platform="wa", page_id="PNID1")
    assert sent  # الرد توصل للزبون
    _assert_no_pii(caplog.text)
