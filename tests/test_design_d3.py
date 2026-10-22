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
    # _rules ما يفرّقش @media (الهاتف: 1fr)، لذلك القاعدة الكاملة كنص
    assert ".plan-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));" in _read(STATIC / "css" / "app.css")
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


# ── 4. الباقة الحالية وتاريخ الانتهاء ──
def test_current_plan_strip_and_pill():
    sec = _plans_section()
    strip = sec[sec.index('id="planCurrentBox"'):]
    strip = strip[:strip.index("</div>")]
    assert 'data-i18n="current_plan"' in strip and 'id="planCurrentName"' in strip and 'id="planCurrentExp"' in strip
    for plan in ("free",) + PAID:
        assert '<span class="plan-current-pill" data-i18n="current_plan" hidden>' in _card(plan), plan
    js = _dashboard_js()
    fn = js[js.index("function highlightCurrentPlan("):]
    fn = fn[:fn.index("\n}\n")]
    assert 'pill.hidden = p!==currentPlan' in fn
    assert 'getElementById("planCurrentName").textContent' in fn  # اسم الباقة نص، ماشي HTML
    for state, key in (("active", "plan_expires_on"), ("expiring", "plan_expires_soon"), ("grace", "plan_grace_until")):
        assert f'"{state}"' in fn and f'"{key}"' in fn, state
    assert 't("plan_no_expiry")' in fn and "fmtDate(" in fn
    date = js[js.index("function fmtDate("):]
    date = date[:date.index("\n}\n")]
    assert "toLocale" not in date  # أرقام لاتينية: 21/11/2026
    r = _css()
    assert r[".plan-current"]["background"] == "var(--brand-light)"
    assert r[".plan-current-exp.warn"]["color"] == "var(--st-pending-fg)"
    assert r[".plan-current-exp.danger"]["color"] == "var(--st-refused-fg)"


# ── 5. الدفع والتواصل والاستعمال ──
SUPPORT_OPEN = """data-on-click="window.open('/static/features/support.html','_blank')\""""


def test_payment_card_keeps_texts_and_has_contact_button():
    sec = _plans_section()
    info = sec[sec.index('<div class="plan-info">'):]
    info = info[:info.index('id="usageBox"')]
    assert 'data-i18n="plan_contact"' in info and 'data-i18n="plan_payment"' in info  # نفس النصوص
    assert "BaridiMob" in info and "CCP" in info
    assert f'<button type="button" class="btn-primary plan-contact" {SUPPORT_OPEN}>' in info
    assert 'data-i18n="contact_us"' in info
    assert "\"window.open('/static/features/support.html','_blank')\"" in _read(STATIC / "js" / "actions.js")


def test_usage_box_uses_dashboard_style():
    js = _dashboard_js()
    fn = js[js.index('var box = document.getElementById("usageBox");'):]
    fn = fn[:fn.index("\n}\n")]
    assert "var(--red)" not in fn and "var(--green)" not in fn and "table-wrap" not in fn
    assert "fmtNum(u.used)" in fn and "fmtNum(u.cap)" in fn and "esc(labels[k]||k)" in fn
    assert 'class="usage-fill\'+cls+\'"' in fn


# ── 6. "اطلب هذه الباقة" → صفحة الدعم بـ ?plan= ──
REQUEST = 'data-on-click="requestPlan(this.dataset.plan)"'


def test_request_button_on_paid_cards_only():
    for plan in PAID:
        card = _card(plan)
        assert f'<button type="button" class="plan-cta" data-plan="{plan}" {REQUEST}>' in card, plan
        assert 'data-i18n="request_plan"' in card
    assert "requestPlan" not in _card("free")
    actions = _read(STATIC / "js" / "actions.js")
    assert '"requestPlan(this.dataset.plan)": function(event){ requestPlan(this.dataset.plan); }' in actions
    js = _dashboard_js()
    fn = js[js.index("function requestPlan("):]
    fn = fn[:fn.index("\n}\n")]
    assert "REQUESTABLE_PLANS.indexOf(plan)<0" in fn  # غير الباقات المعروفة
    assert "window.open(\"/static/features/support.html?plan=\"+encodeURIComponent(plan), \"_blank\")" in fn
    assert 'var REQUESTABLE_PLANS = ["starter","pro","business","early"];' in js
    hl = js[js.index("function highlightCurrentPlan("):]
    hl = hl[:hl.index("\n}\n")]
    assert "cta.hidden = p===currentPlan" in hl  # باقتك الحالية: بلا زر


def test_support_page_prefills_the_plan_safely():
    html = _read(STATIC / "features" / "support.html")
    assert 'var PLAN_NAMES = {starter:"Starter", pro:"Pro", business:"Business", early:"أوائل التجار"};' in html
    js = html[html.index("var PLAN_NAMES"):]
    js = js[:js.index("})();") + 5]
    assert 'new URLSearchParams(location.search).get("plan")' in js
    assert "Object.prototype.hasOwnProperty.call(PLAN_NAMES, plan)" in js  # قيمة من القائمة فقط
    assert '.value = "نحب نشترك في باقة "+PLAN_NAMES[plan]' in js  # نص فـ textarea، بلا innerHTML
    assert "innerHTML" not in js and 'getElementById("s_type").value = "other"' in js


# ── 7. الهاتف: وحدة تحت الأخرى، وPro الأولى ──
def test_mobile_stacks_cards_with_pro_first():
    css = _read(STATIC / "css" / "app.css")
    block = css[css.index("@media (max-width:640px){.plan-grid"):]
    block = block[:block.index("}}") + 2]
    assert ".plan-grid{grid-template-columns:1fr}" in block and ".plan-pro{order:-1}" in block
    sec = _plans_section()  # ترتيب الـ HTML يبقى free، starter، pro، business (الحاسوب)
    order = [sec.index(f'id="plan_{p}"') for p in ("free", "starter", "pro", "business", "early")]
    assert order == sorted(order)


# ── لقطة 1280: الأربع بطاقات فسطر واحد، والعنوان مرة وحدة ──
def test_four_cards_fit_one_row_on_a_computer():
    """المحتوى ~966px: بـ 240px تطلع 3 بطاقات وBusiness وحدها فسطر ثاني."""
    css = _read(STATIC / "css" / "app.css")
    m = re.search(r"\.plan-grid\{display:grid;grid-template-columns:repeat\(auto-fit,minmax\(min\(100%,(\d+)px\),1fr\)\);gap:(\d+)px", css)
    card_min, gap = int(m.group(1)), int(m.group(2))
    assert 4 * card_min + 3 * gap <= 966
    r = _css()
    assert r[".plan-card"]["padding"] == "24px"
    assert '<h2 class="plans-title"' not in _plans_section()  # #pageTitle فيه "الاشتراكات" من قبل
