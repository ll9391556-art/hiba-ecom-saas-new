# -*- coding: utf-8 -*-
"""المهمة 1 (design/PLAN.md): الباقات والأسعار — تعريف الباقات، enterprise→business، lifetime
مخفي، سقف ردود البوت، تاريخ الانتهاء، والشحن "قريبًا"."""
import re

import pytest

from tests import fakes
from tests.frontend import STATIC, page_source

ADMIN = {"X-Admin-Key": "dummy-admin-key"}
DASH = page_source("index.html")


def _plan(client, owner):
    return client.get("/api/getUserPlan", headers=owner["headers"]).get_json()["data"]


# ── A. تعريف الباقات والأسعار ─────────────────────────────
def test_plan_definitions(app):
    P = app.PLANS
    free, starter, pro, business, early = (P[k] for k in ("free", "starter", "pro", "business", "early"))
    assert free["dashboard"] and free["orders"]
    assert not any(free[f] for f in ("store", "tracking", "export", "bot", "landing", "coupons", "team"))
    assert starter["store"] and starter["tracking"] and starter["export"] and starter["templates"] == 2
    assert not any(starter[f] for f in ("bot", "landing", "integrations", "coupons", "team"))
    assert pro["bot"] and pro["botMsgCap"] == 1500 and pro["landing"] and pro["integrations"]
    assert pro["coupons"] and pro["templates"] == "all" and pro["store"] and pro["export"]
    assert not pro["team"] and not pro["vip"]
    assert business["botMsgCap"] == 5000 and business["team"] and business["vip"] and business["coupons"]
    assert {k: v for k, v in early.items() if k not in ("label", "price")} == \
           {k: v for k, v in pro.items() if k not in ("label", "price")}
    assert [P[k]["price"] for k in ("free", "starter", "pro", "business", "early")] == [
        {"monthly": 0}, {"monthly": 1500}, {"monthly": 2900, "yearly": 24900}, {"monthly": 4900}, {"yearly": 19900}]
    for k in ("free", "starter", "pro", "business", "early"):
        assert "orderCap" not in P[k]


def test_frontend_plan_features_come_from_the_server():
    """خريطة الميزات وحدة فقط (PLANS فالسيرفر) — الواجهة كتقرا features من /api/getUserPlan."""
    fn = DASH[DASH.index("function planHas("):]
    fn = fn[:fn.index("\n}\n")]
    assert "PLAN_FEATURES" in fn and "enterprise" not in fn and "starter" not in fn
    assert "PLAN_FEATURES = r.data.features" in DASH


def _card_prices(html):
    return {m.group(1): int(m.group(2).replace(",", ""))
            for m in re.finditer(r'data-price="([a-z]+-[a-z]+)">([\d,]+)<', html)}


def test_plans_page_shows_the_new_prices(app):
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    want = {f"{k}-{period}": v for k in ("free", "starter", "pro", "business", "early")
            for period, v in app.PLANS[k]["price"].items()}
    assert _card_prices(html) == want
    for k in ("free", "starter", "pro", "business", "early"):
        assert f'id="plan_{k}"' in html
    assert 'id="plan_enterprise"' not in html
    assert "BaridiMob" in html and "CCP" in html


def test_admin_can_activate_business_and_early(client, db, seed_owner):
    owner = seed_owner(plan="free")
    for plan in ("business", "early"):
        r = client.post("/api/updateUserPlan", headers=ADMIN,
                        json={"userId": owner["uid"], "username": owner["username"], "plan": plan})
        assert r.status_code == 200 and db.get(f"users/{owner['username']}/plan") == plan
        assert _plan(client, owner)["features"]["bot"] is True
    admin = client.get("/admin").get_data(as_text=True)
    assert '<option value="business">' in admin and '<option value="early">' in admin
