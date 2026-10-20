# -*- coding: utf-8 -*-
"""/webhook — توقيع إنستغرام (Instagram Login) يتحقق بسر منفصل INSTAGRAM_APP_SECRET."""
import hashlib
import hmac
import json
import logging

import pytest

META = "dummy-secret"        # = META_APP_SECRET فـ conftest
IG = "dummy-ig-secret"

IG_BODY = json.dumps({"object": "instagram", "entry": [{"id": "IG1", "messaging": [
    {"sender": {"id": "IGSID9876"}, "message": {"mid": "m1", "text": "salam"}}]}]}).encode()


def _sig(key, body):
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def handled(app, monkeypatch):
    """يشغّل handle() متزامن ويسجّل نداءات process_bg بلا Gemini ولا شبكة."""
    class SyncExecutor:
        def submit(self, fn, *a, **kw):
            fn(*a, **kw)

    calls = []
    bot = {"User_ID": "u1", "plan": "pro", "page_id_FB": "PAGE1",
           "Page_ID_instgram": "IG1", "instgram_access_token": "ig-tok"}
    monkeypatch.setattr("services.bot._executor", SyncExecutor())
    monkeypatch.setattr("services.bot.get_user_settings", lambda cid: bot if cid == "IG1" else None)
    monkeypatch.setattr("services.bot.process_bg", lambda sid, txt, *a, **kw: calls.append((sid, txt, a)))
    return calls


def _post(client, body, sig):
    return client.post("/webhook", data=body, content_type="application/json",
                       headers={"X-Hub-Signature-256": sig})


def test_instagram_signed_with_instagram_secret_is_handled(client, monkeypatch, handled):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", IG)
    r = _post(client, IG_BODY, _sig(IG, IG_BODY))
    assert r.status_code == 200
    assert handled and handled[0][0] == "IGSID9876" and handled[0][1] == "salam"
    assert handled[0][2][-2] == "ig"  # platform


def test_meta_secret_still_accepted(client, monkeypatch, handled):
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", IG)
    assert _post(client, IG_BODY, _sig(META, IG_BODY)).status_code == 200
    assert handled


def test_wrong_key_rejected_and_not_handled(client, monkeypatch, handled, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("INSTAGRAM_APP_SECRET", IG)
    r = _post(client, IG_BODY, _sig("wrong-key", IG_BODY))
    assert r.status_code == 403
    assert not handled
    assert "سنستمر للمعالجة" not in caplog.text       # ما يكذبش السجل
    assert "object=instagram" in caplog.text          # تلميح آمن على المنتج اللي فشل
    assert "salam" not in caplog.text and "IGSID9876" not in caplog.text


def test_instagram_secret_unset_keeps_old_behaviour(client, monkeypatch, handled):
    monkeypatch.delenv("INSTAGRAM_APP_SECRET", raising=False)
    assert _post(client, IG_BODY, _sig(IG, IG_BODY)).status_code == 403
    assert _post(client, IG_BODY, _sig(META, IG_BODY)).status_code == 200


def test_no_secrets_fails_closed(app, monkeypatch):
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("INSTAGRAM_APP_SECRET", raising=False)
    assert app.verify_sig(IG_BODY, {"X-Hub-Signature-256": _sig("", IG_BODY)}) is False
