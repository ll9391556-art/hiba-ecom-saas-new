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


# ── B. enterprise → business (تطبيع عند القراءة + backfill فـ rebuildIndexes) ──
def test_enterprise_accounts_work_as_business(client, app, seed_owner):
    owner = seed_owner(plan="Enterprise")
    data = _plan(client, owner)
    assert data["plan"] == "business" and data["features"]["team"] and data["features"]["botMsgCap"] == 5000
    assert app.get_user_plan(owner["uid"]) == "business" and app.planHas_server(owner["uid"], "team")
    assert app._bot_allowed_for({"plan": "enterprise"}) is True
    assert app._plan_cap(owner["uid"], "botMsgCap") == 5000
    r = client.post("/api/team/addMember", headers=owner["headers"],
                    json={"username": "m1", "password": "dummy-pass-123"})
    assert r.status_code == 200


def test_admin_enterprise_is_stored_as_business(client, db, seed_owner):
    owner = seed_owner(plan="free")
    assert _set_plan(client, owner, "enterprise").get_json()["data"]["plan"] == "business"
    assert db.get("users/owner1/plan") == "business"
    assert "enterprise" not in client.get("/admin").get_data(as_text=True).lower()


def test_rebuild_indexes_migrates_enterprise_to_business(client, db):
    db.set("users", {"a": {"Username": "a", "User_ID": "1", "plan": "enterprise", "Gemini_api_key": "k"},
                     "b": {"Username": "b", "User_ID": "2", "plan": "pro"}})
    for _ in range(2):  # idempotent
        res = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["users"]
        assert db.get("users/a") == {"Username": "a", "User_ID": "1", "plan": "business", "Gemini_api_key": "k"}
        assert db.get("users/b/plan") == "pro"
    assert res["plansMigrated"] == 0


# ── C. lifetime: ما يتباعش جديد، والمشتركين الحاليين يبقاو يخدمو ──
@pytest.mark.parametrize("plan", ["lifetime", "full"])
def test_new_lifetime_accounts_are_refused(client, db, plan):
    r = _create(client, "l1", plan)
    assert r.status_code == 400 and db.get("users/l1") is None
    assert (db.get("counters/lifetimeAccounts") or 0) == 0


def test_switching_to_lifetime_is_refused_but_existing_ones_keep_it(client, db, seed_owner):
    newbie = seed_owner(plan="pro")
    assert _set_plan(client, newbie, "lifetime").status_code == 400 and db.get("users/owner1/plan") == "pro"
    old = seed_owner(username="old", uid="2002", plan="lifetime")
    db.set("counters/lifetimeAccounts", 1)
    assert _set_plan(client, old, "lifetime").status_code == 200
    assert _set_plan(client, old, "full").status_code == 200 and db.get("counters/lifetimeAccounts") == 1
    data = _plan(client, old)
    assert data["plan"] == "full" and data["features"]["bot"] and data["features"]["team"]
    assert data["features"]["botMsgCap"] == 3000


def test_lifetime_is_gone_from_the_ui(client):
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="plan_lifetime"' not in html and "lifetimeSlotsBadge" not in DASH
    admin = client.get("/admin").get_data(as_text=True)
    assert '<option value="lifetime">' not in admin and "lifetimeSlotsDisplay" not in admin


# ── D. سقف ردود البوت الشهري ─────────────────────────────
class _Sync:
    def submit(self, fn, *a, **kw):
        fn(*a, **kw)


@pytest.fixture
def bot_run(app, monkeypatch, seed_owner):
    monkeypatch.setattr("services.bot._executor", _Sync())
    fakes.GEMINI_CALLS.clear()
    fakes.GEMINI_RESPONDER["fn"] = lambda model, contents, config: "مرحبا بيك"
    owner = seed_owner(plan="pro")
    bot = {"User_ID": owner["uid"], "Gemini_api_key": "dummy-gemini-key", "plan": "pro"}
    sent = []

    def run(text="salam"):
        app.process_bg("SID1", text, bot, lambda msg: sent.append(msg) or True)
    run.sent, run.owner = sent, owner
    run.path = f"data/{owner['uid']}/usage/{app._usage_month_key()}/botMsgCount"
    return run


def test_bot_stops_silently_at_the_cap(db, bot_run):
    db.set(bot_run.path, 1499)
    bot_run()
    assert bot_run.sent == ["مرحبا بيك"] and db.get(bot_run.path) == 1500
    calls = len(fakes.GEMINI_CALLS)
    bot_run("salam 2")
    assert bot_run.sent == ["مرحبا بيك"]            # ما كاين حتى رد ولا اعتذار للزبون
    assert len(fakes.GEMINI_CALLS) == calls and db.get(bot_run.path) == 1500


def test_reservation_is_one_atomic_step(app, db, bot_run, monkeypatch):
    uid = bot_run.owner["uid"]
    assert [app._reserve_usage(uid, "botMsgCount", 2) for _ in range(3)] == [True, True, False]
    assert db.get(bot_run.path) == 2
    db.set(bot_run.path, 0)
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("check-then-increment"))
    monkeypatch.setattr("services.bot._under_cap", boom, raising=False)
    monkeypatch.setattr("services.bot._increment_usage", boom, raising=False)
    bot_run()
    assert db.get(bot_run.path) == 1


def test_gemini_failure_gives_the_reply_back(db, bot_run, monkeypatch):
    monkeypatch.setattr("services.bot.sleep", lambda s: None)
    db.set(bot_run.path, 10)
    fakes.GEMINI_RESPONDER["fn"] = lambda *a: (_ for _ in ()).throw(RuntimeError("down"))
    bot_run()
    assert db.get(bot_run.path) == 10


def test_messages_still_reach_conversations_at_the_cap(client, app, db, bot_run, monkeypatch):
    import hashlib, hmac, json
    uid = bot_run.owner["uid"]
    bot = {"User_ID": uid, "Gemini_api_key": "dummy-gemini-key", "plan": "pro", "whtsapp_token": "wa-tok"}
    monkeypatch.setattr("services.bot.get_user_settings", lambda cid: bot if cid == "PNID" else None)
    outgoing = []
    monkeypatch.setattr("services.bot.send_whatsapp_message", lambda *a: outgoing.append(a) or True)
    db.set(bot_run.path, 1500)
    body = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "PNID"},
        "messages": [{"from": "213555000111", "type": "text", "text": {"body": "salam"}}]}}]}]}).encode()
    sig = hmac.new(b"dummy-secret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", data=body, content_type="application/json",
                    headers={"X-Hub-Signature-256": "sha256=" + sig})
    assert r.status_code == 200
    msgs = list((db.get(f"conversations/{uid}/213555000111") or {}).values())
    assert [m["direction"] for m in msgs] == ["in"] and msgs[0]["text"] == "salam"
    assert fakes.GEMINI_CALLS == [] and outgoing == []


def test_get_user_plan_reports_bot_usage(client, db, bot_run):
    db.set(bot_run.path, 1200)
    assert _plan(client, bot_run.owner)["usage"]["botMsgs"] == {"used": 1200, "cap": 1500}


def test_dashboard_warns_at_80_percent_and_at_the_cap():
    fn = DASH[DASH.index("function renderPlanAlerts("):]
    fn = fn[:fn.index("\n}\n")]
    assert "0.8" in fn and "botMsgs" in fn and "bot_cap_reached" in fn and "bot_usage_x_of_y" in fn
    assert "renderPlanAlerts()" in DASH[DASH.index("async function loadUserPlan("):]
    assert 'id="planAlerts"' in (STATIC / "index.html").read_text(encoding="utf-8")
    assert "استعملت {x} من {y} رد هذا الشهر" in DASH
