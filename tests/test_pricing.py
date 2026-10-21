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


# ── A. أوائل التجار: عدّاد خاص counters/earlyAccounts بحد 50 ─────
def _create(client, username, plan):
    return client.post("/api/admin/createClient", headers=ADMIN,
                       json={"username": username, "password": "dummy-pass-123", "plan": plan})


def _set_plan(client, owner, plan, **extra):
    return client.post("/api/updateUserPlan", headers=ADMIN,
                       json={"userId": owner["uid"], "username": owner["username"], "plan": plan, **extra})


def test_early_slots_are_capped_on_create(client, db, monkeypatch):
    monkeypatch.setattr("routes.admin.EARLY_MAX_SLOTS", 2)
    assert _create(client, "e1", "early").status_code == 200
    assert _create(client, "e2", "early").status_code == 200
    assert db.get("counters/earlyAccounts") == 2
    assert _create(client, "e3", "early").status_code == 409 and db.get("users/e3") is None
    assert (db.get("counters/lifetimeAccounts") or 0) == 0


def test_early_slots_follow_plan_changes(client, db, seed_owner, monkeypatch):
    monkeypatch.setattr("routes.admin.EARLY_MAX_SLOTS", 1)
    a, b = seed_owner(), seed_owner(username="owner2", uid="1002")
    assert _set_plan(client, a, "early").status_code == 200 and db.get("counters/earlyAccounts") == 1
    assert _set_plan(client, a, "early").status_code == 200 and db.get("counters/earlyAccounts") == 1
    r = _set_plan(client, b, "early")
    assert r.status_code == 409 and db.get("users/owner2/plan") == "pro"
    assert _set_plan(client, a, "pro").status_code == 200 and (db.get("counters/earlyAccounts") or 0) == 0
    assert _set_plan(client, b, "early").status_code == 200


def test_get_user_plan_reports_early_slots_left(client, db, seed_owner):
    owner = seed_owner()
    db.set("counters/earlyAccounts", 12)
    assert _plan(client, owner)["earlySlotsLeft"] == 50 - 12


def test_rebuild_indexes_recounts_early_accounts(client, db):
    db.set("users", {"a": {"Username": "a", "User_ID": "1", "plan": "early"},
                     "b": {"Username": "b", "User_ID": "2", "plan": "pro"}})
    db.set("counters/earlyAccounts", 9)
    res = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["users"]
    assert res["earlyAccounts"] == 1 and db.get("counters/earlyAccounts") == 1


def test_frontend_shows_early_slots_left():
    fn = DASH[DASH.index("function highlightCurrentPlan("):]
    assert "EARLY_SLOTS_LEFT" in fn[:fn.index("\n}\n")] and "r.data.earlySlotsLeft" in DASH
