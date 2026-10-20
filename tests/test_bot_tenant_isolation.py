# -*- coding: utf-8 -*-
"""SEC-005 — سجل البوت وفحص الطلبات المكررة وحد المعدل مربوطين بالتاجر، مش بالزبون وحدو."""
import hashlib
import hmac
import json

import pytest

from tests import fakes

SID = "213555987654"  # واتساب: sender_id = رقم الزبون، نفسو عند كل التجار
A = {"User_ID": "1001", "Gemini_api_key": "dummy-gemini-key", "plan": "pro"}
B = {"User_ID": "2002", "Gemini_api_key": "dummy-gemini-key", "plan": "pro"}


def _prompt_texts():
    return [p.text for call in fakes.GEMINI_CALLS for p in call["contents"] if getattr(p, "text", None)]


@pytest.fixture
def gemini_echo():
    fakes.GEMINI_CALLS.clear()
    fakes.GEMINI_RESPONDER["fn"] = lambda model, contents, config: "مرحبا بيك"


def test_history_is_separate_per_merchant(app, db, gemini_echo):
    app.ask_gemini(SID, "اسمي Amina وعنواني 12 Rue Secrete", A)
    fakes.GEMINI_CALLS.clear()
    app.ask_gemini(SID, "سلام", B)
    prompt_b = "\n".join(_prompt_texts())
    assert "Rue Secrete" not in prompt_b and "Amina" not in prompt_b
    assert db.get(f"chats/{A['User_ID']}/{SID}")
    assert db.get(f"chats/{B['User_ID']}/{SID}")


def test_history_still_works_within_one_merchant(app, gemini_echo):
    app.ask_gemini(SID, "نحب الصاك الأحمر", A)
    fakes.GEMINI_CALLS.clear()
    app.ask_gemini(SID, "شحال السعر؟", A)
    assert "الصاك الأحمر" in "\n".join(_prompt_texts())


def test_legacy_chats_not_read_and_not_deleted(app, db, gemini_echo):
    db.set(f"chats/{SID}/-legacy1", {"role": "user", "content": "OLD-SECRET-ADDRESS", "timestamp": 1})
    app.ask_gemini(SID, "سلام", A)
    assert "OLD-SECRET-ADDRESS" not in "\n".join(_prompt_texts())
    assert db.get(f"chats/{SID}/-legacy1")["content"] == "OLD-SECRET-ADDRESS"


def test_no_merchant_uid_means_no_shared_history(app, db, gemini_echo):
    db.set(f"chats/{SID}/-legacy1", {"role": "user", "content": "OLD-SECRET-ADDRESS", "timestamp": 1})
    app.ask_gemini(SID, "سلام", {"Gemini_api_key": "dummy-gemini-key"})
    assert "OLD-SECRET-ADDRESS" not in "\n".join(_prompt_texts())
    assert list((db.get(f"chats/{SID}") or {}).keys()) == ["-legacy1"]


ORDER = {"product": "Sac", "quantity": "1", "name": "Amina", "phone": "0555123456",
         "city": "Alger", "delivery_type": "منزل", "address": "12 Rue"}


def test_duplicate_order_check_is_per_merchant(app, db):
    assert app.save_order_from_bot(dict(ORDER), A, SID) is True
    assert app.save_order_from_bot(dict(ORDER), B, SID) is True    # تاجر آخر: طلب جديد
    assert app.save_order_from_bot(dict(ORDER), A, SID) is False   # نفس التاجر: مكرر
    assert len(db.get(f"data/{A['User_ID']}/orders") or {}) == 1
    assert len(db.get(f"data/{B['User_ID']}/orders") or {}) == 1


# ── حد المعدل فـ webhook واتساب ─────────────────────────────
def _wa_body(phone_id, text):
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_id},
        "messages": [{"from": SID, "type": "text", "text": {"body": text}}]}}]}]}).encode()


@pytest.fixture
def wa_calls(app, monkeypatch):
    class SyncExecutor:
        def submit(self, fn, *a, **kw):
            fn(*a, **kw)

    bots = {"PNID_A": {**A, "whtsapp_token": "wa-tok-a"}, "PNID_B": {**B, "whtsapp_token": "wa-tok-b"}}
    calls = []
    monkeypatch.setattr("services.bot._executor", SyncExecutor())
    monkeypatch.setattr("services.bot.get_user_settings", lambda cid: bots.get(cid))
    monkeypatch.setattr("services.bot.process_bg", lambda sid, txt, bot, *a, **kw: calls.append(bot["User_ID"]))
    return calls


def _post(client, body):
    sig = hmac.new(b"dummy-secret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", data=body, content_type="application/json",
                    headers={"X-Hub-Signature-256": "sha256=" + sig})
    assert r.status_code == 200


def test_rate_limit_is_per_merchant(client, wa_calls):
    _post(client, _wa_body("PNID_A", "salam"))
    _post(client, _wa_body("PNID_B", "salam"))
    assert wa_calls == ["1001", "2002"]


def test_rate_limit_still_applies_within_one_merchant(client, wa_calls):
    _post(client, _wa_body("PNID_A", "salam"))
    _post(client, _wa_body("PNID_A", "salam 2"))
    assert wa_calls == ["1001"]
