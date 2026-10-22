# -*- coding: utf-8 -*-
"""Design D3 — صفحة الاشتراكات كيما قسم الأسعار فـ design/Landing.dc.html، بالباقات تاع PLANS.
المرجع: design/PLAN.md (D3) و design/reports/D3-plan.md. التصميم فقط: بلا تغيير فـ PLANS ولا الـ API."""
import re

from tests.frontend import STATIC
from tests.test_design_d1 import DARK, _rules

PAID = ("starter", "pro", "business", "early")


def _read(path):
    return path.read_text(encoding="utf-8")


def _index():
    return _read(STATIC / "index.html")


def _plans_section():
    html = _index()
    return html[html.index('<div id="sec_plans"'):html.index('<div id="sec_settings"')]


def _card(plan):
    sec = _plans_section()
    at = sec.index(f'id="plan_{plan}"')
    start = sec.rindex("<div", 0, at)
    nxt = [sec.find(f'id="plan_{p}"', at + 1) for p in ("free",) + PAID]
    ends = [sec.rindex("<div", 0, n) for n in nxt if n > at]
    return sec[start:min(ends)] if ends else sec[start:]


def _css():
    return _rules(_read(STATIC / "css" / "app.css"))


def _dashboard_js():
    return _read(STATIC / "js" / "dashboard.js")


# ── 1. البطاقات كيما Landing.dc.html ──
def test_plan_cards_follow_the_landing_design():
    sec = _plans_section()
    assert 'class="row' not in sec and 'class="col-' not in sec  # بلا Bootstrap
    assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", sec)  # بلا إيموجي
    assert '<div class="plan-grid">' in sec
    for plan in ("free",) + PAID:
        assert f'id="plan_{plan}"' in sec, plan
    assert re.search(r'<div class="plan-card plan-pro" id="plan_pro"', sec)
    assert re.search(r'<div class="plan-card plan-business" id="plan_business"', sec)
    pro = _card("pro")
    assert '<span class="plan-top" data-i18n="most_popular">' in pro
    r = _css()
    assert r[".plan-card"]["border-radius"] == "28px" and r[".plan-card"]["background"] == "var(--white)"
    assert r[".plan-pro"]["background"] == "var(--brand)" and r[".plan-pro"]["color"] == "#fff"
    assert r[".plan-business"]["border"] == "2px solid var(--brand)"
    assert r[".plan-top"]["background"] == "var(--volt)" and r[".plan-top"]["color"] == "var(--ink)"
    assert r[".plan-pro .plan-feature svg"]["color"] == "var(--volt)"
    assert r[".plan-grid"]["grid-template-columns"] == "repeat(auto-fit,minmax(min(100%,240px),1fr))"
    css = _read(STATIC / "css" / "app.css").lower()
    block = css[css.index(".plan-grid"):css.index("/* /plans */")]
    assert not any(d in block for d in DARK) and not any(d in sec.lower() for d in DARK)
    assert "#f59e0b" not in sec.lower()


# ── 2. الأسعار بلا فاصل آلاف ──
CORE = _read(STATIC / "js" / "core.js")


def _i18n(lang, key):
    block = re.search(r"\n  %s:\{(.*?)\n  \}" % lang, CORE, re.S).group(1)
    m = re.search(r'[,{\s]%s:"([^"]*)"' % key, block)
    return m.group(1) if m else None


def test_prices_have_no_thousands_separator(app):
    sec = _plans_section()
    prices = dict(re.findall(r'data-price="([a-z]+-[a-z]+)">([^<]*)<', sec))
    want = {f"{k}-{period}": str(v) for k in ("free",) + PAID for period, v in app.PLANS[k]["price"].items()}
    assert prices == want  # "2900"، ماشي "2,900"
    assert sec.count('data-i18n="unit_month"') == 4 and "<small>DZD</small>" not in sec  # free تاني بالوحدة
    units = {"AR": ("دج / شهر", "دج / سنة"), "FR": ("DA / mois", "DA / an"), "EN": ("DZD / month", "DZD / year")}
    for lang, (month, year) in units.items():
        assert _i18n(lang, "unit_month") == month and _i18n(lang, "unit_year") == year, lang
        for key in ("pf_bot_1500", "pf_bot_5000"):
            assert not re.search(r"\d[ ,\u00a0\u202f]\d{3}", _i18n(lang, key)), (lang, key)


# ── 3. بطاقة أوائل التجار ──
def test_early_card_like_the_landing_offer(app):
    card = _card("early")
    assert '<span class="plan-offer" data-i18n="early_offer">' in card
    assert 'id="earlySlotsBadge"' in card and 'id="earlyInsteadOf"' in card
    r = _css()
    assert r[".plan-early"]["border"] == "2px solid var(--brand)" and r[".plan-offer"]["background"] == "var(--volt)"
    js = _dashboard_js()
    fn = js[js.index("function highlightCurrentPlan("):]
    fn = fn[:fn.index("\n}\n")]
    # "بدل 34800": سعر Pro الشهري × 12، من data-price (اللي test_pricing يربطو بـ PLANS)، ماشي مكتوب باليد
    assert 'querySelector(\'[data-price="pro-monthly"]\')' in fn and "*12" in fn
    assert "34800" not in _index() + js + CORE
    assert app.PLANS["pro"]["price"]["monthly"] * 12 == 34800  # القيمة اللي تبان اليوم
    assert 't("instead_of_year")' in fn
    assert '"🔥' not in fn and 't("early_full")' in fn  # بلا إيموجي، و"اكتملت البلايص" عند 0
    assert "highlightCurrentPlan" in CORE[CORE.index("function applyLang("):CORE.index("function setLang(")]
