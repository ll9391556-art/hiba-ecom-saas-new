# -*- coding: utf-8 -*-
"""المهمة 1.5 (design/PLAN.md): تنسيق ردود البوت — العملة من إعدادات المتجر (دج افتراضياً)،
الأسعار بلا ".0" وبفاصل الآلاف، بلا Markdown فماسنجر/إنستغرام، وأسماء منتجات نظيفة فالـ prompt."""
import pytest

from tests import fakes

UID = "1001"
BOT = {"User_ID": UID, "Gemini_api_key": "dummy-gemini-key", "plan": "pro"}


@pytest.fixture
def gemini(app):
    fakes.GEMINI_CALLS.clear()
    fakes.GEMINI_RESPONDER["fn"] = lambda model, contents, config: "مرحبا"
    return fakes.GEMINI_CALLS


def _system_prompt(calls):
    return getattr(calls[-1]["config"], "system_instruction", "") or ""


# ── 1. العملة ────────────────────────────────────────────
def test_products_and_prompt_use_dinar_by_default(app, db, gemini):
    db.set(f"data/{UID}/products/Sac", {"name": "Sac", "sell": 2500, "init": 5, "category": "Sacs"})
    text = app.get_products_text(BOT)
    assert "دج" in text and "درهم" not in text
    app.ask_gemini("SID1", "شحال الصاك؟", BOT)
    prompt = _system_prompt(gemini)
    assert "دج" in prompt and "الدينار الجزائري" in prompt
    assert "لا تستعمل درهم" in prompt


def test_currency_follows_store_settings(app, db, gemini):
    db.set(f"data/{UID}/storeSettings/currency", "EUR")
    db.set(f"data/{UID}/products/Sac", {"name": "Sac", "sell": 25, "init": 5})
    assert "€" in app.get_products_text(BOT) and "دج" not in app.get_products_text(BOT)
    app.ask_gemini("SID1", "prix ?", BOT)
    assert "€" in _system_prompt(gemini)
