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
