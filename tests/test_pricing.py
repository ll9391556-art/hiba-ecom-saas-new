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


# ── E. تاريخ انتهاء الاشتراك + 3 أيام سماح ─────────────────
import time as _time

DAY = 86_400_000


def _now():
    return int(_time.time() * 1000)


@pytest.mark.parametrize("offset,state,plan", [
    (10 * DAY, "active", "pro"),
    (2 * DAY, "expiring", "pro"),      # تنبيه قبل الانتهاء بـ 3 أيام
    (-1 * DAY, "grace", "pro"),        # خلال أيام السماح: الباقة باقية
    (-4 * DAY, "expired", "free"),     # بعد السماح: free
])
def test_subscription_expiry_states(client, app, seed_owner, offset, state, plan):
    exp = _now() + offset
    owner = seed_owner(plan="pro", plan_period="monthly", plan_expires_at=exp)
    data = _plan(client, owner)
    sub = data["subscription"]
    assert sub["state"] == state and data["plan"] == plan and app.get_user_plan(owner["uid"]) == plan
    assert sub["expiresAt"] == exp and sub["graceEndsAt"] == exp + 3 * DAY and sub["period"] == "monthly"
    assert data["features"]["bot"] is (plan == "pro")
    assert app._bot_allowed_for({"plan": "pro", "plan_expires_at": exp}) is (plan == "pro")
    if state == "expired":
        assert sub["plan"] == "pro"  # الباقة اللي انتهات، باش اللوحة تقول للتاجر واش كان عندو


@pytest.mark.parametrize("value", [None, 0, "", "abc", -5])
def test_accounts_without_expiry_never_expire(client, seed_owner, value):
    extra = {} if value is None else {"plan_expires_at": value}
    owner = seed_owner(plan="pro", **extra)
    data = _plan(client, owner)
    assert data["plan"] == "pro" and data["subscription"]["state"] == "none"


def test_admin_sets_the_duration(client, db, seed_owner):
    owner = seed_owner(plan="free")
    rec = lambda: db.get("users/owner1")
    before = _now()
    assert _set_plan(client, owner, "pro", duration="month").status_code == 200
    assert rec()["plan_period"] == "monthly" and before + 30 * DAY <= rec()["plan_expires_at"] <= _now() + 30 * DAY
    first = rec()["plan_expires_at"]
    assert _set_plan(client, owner, "pro", duration="month").status_code == 200   # تجديد قبل الانتهاء: يتزاد
    assert rec()["plan_expires_at"] == first + 30 * DAY
    assert _set_plan(client, owner, "business", duration="year").status_code == 200
    assert rec()["plan_period"] == "yearly" and rec()["plan_expires_at"] >= _now() + 364 * DAY
    assert rec()["plan_expires_at"] <= _now() + 365 * DAY  # باقة أخرى: من اليوم، ماشي من الانتهاء القديم
    assert _set_plan(client, owner, "pro", duration="none").status_code == 200
    assert "plan_expires_at" not in rec() and "plan_period" not in rec()
    assert _set_plan(client, owner, "pro", duration="week").status_code == 400
    assert _set_plan(client, owner, "early").status_code == 200 and rec()["plan_period"] == "yearly"
    assert _set_plan(client, owner, "free", duration="month").status_code == 200 and "plan_expires_at" not in rec()


def test_create_client_with_duration(client, db):
    r = client.post("/api/admin/createClient", headers=ADMIN, json={
        "username": "d1", "password": "dummy-pass-123", "plan": "starter", "duration": "month"})
    assert r.status_code == 200 and db.get("users/d1/plan_period") == "monthly"


def test_merchant_cannot_change_the_expiry(client, db, seed_owner):
    exp = _now() + DAY
    owner = seed_owner(plan="pro", plan_expires_at=exp, plan_period="monthly")
    client.post("/api/updateBotSettings", headers=owner["headers"],
                json={"data": {"plan_expires_at": exp + 999 * DAY, "plan_period": "yearly", "AI_instructions": "x"}})
    client.post("/api/saas", headers=owner["headers"],
                json={"action": "updateBotSettings", "payload": {"plan_expires_at": 0}})
    assert db.get("users/owner1/plan_expires_at") == exp and db.get("users/owner1/plan_period") == "monthly"


def test_list_clients_shows_expiry(client, seed_owner):
    exp = _now() + DAY
    seed_owner(plan="pro", plan_expires_at=exp, plan_period="monthly")
    row = client.get("/api/admin/listClients", headers=ADMIN).get_json()["data"][0]
    assert row["planExpiresAt"] == exp and row["planPeriod"] == "monthly"


def test_dashboard_warns_before_and_during_grace(client):
    fn = DASH[DASH.index("function renderPlanAlerts("):]
    fn = fn[:fn.index("\n}\n")]
    for key in ("sub_expiring", "sub_grace", "sub_expired", "SUBSCRIPTION"):
        assert key in fn
    assert "SUBSCRIPTION = r.data.subscription" in DASH
    admin = client.get("/admin").get_data(as_text=True)
    assert 'id="newDurationLocal"' in admin and "duration" in admin


# ── F. الشحن: "قريبًا" — حتى إعداد ما يتحفظ ما دام الربط ما خدامش ──
def test_shipping_endpoints_say_coming_soon(client, db, seed_owner):
    owner = seed_owner(plan="business")
    r = client.post("/api/shipping/connect", headers=owner["headers"],
                    json={"provider": "yalidine", "apiId": "dummy-id", "apiToken": "dummy-token"})
    assert r.status_code == 503 and "قريب" in r.get_json()["message"]
    assert db.get(f"data/{owner['uid']}/integrations/shipping") is None
    db.set(f"data/{owner['uid']}/orders/ORD-1", {"id": "ORD-1", "status": "Confirmed"})
    r = client.post("/api/shipping/createShipment", headers=owner["headers"], json={"orderId": "ORD-1"})
    assert r.status_code == 503
    # اللي ربط من قبل يقدر يشوف الحالة ويفك الربط
    assert client.get("/api/shipping/status", headers=owner["headers"]).status_code == 200
    assert client.post("/api/shipping/disconnect", headers=owner["headers"], json={}).status_code == 200


def test_shipping_ui_is_coming_soon():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    nav = html[html.index('data-i18n="nav_shipping"') - 400:html.index('data-i18n="nav_shipping"') + 200]
    assert "shipping.html" not in nav and 'data-i18n="soon"' in nav and "nav-item disabled" in nav
    page = (STATIC / "features" / "shipping.html").read_text(encoding="utf-8")
    assert "<input" not in page and "/shipping/connect" not in page and "قريبًا" in page


# ── الفريق غير فـ business: الأعضاء الحاليين عند باقة أخرى يتوقفو بلا مسح ──
def _member_login(client, username="member1"):
    return client.post("/api/login", json={"username": username, "password": "dummy-pass-123"})


def test_members_of_a_plan_without_team_cannot_log_in(client, db, seed_owner, seed_member):
    owner = seed_owner(plan="pro")
    seed_member(owner)
    r = _member_login(client)
    assert r.status_code == 403 and "Business" in r.get_json()["message"]
    assert db.get("team_users/member1/active") is True and db.get(f"data/{owner['uid']}/teamMembers/member1")
    assert _set_plan(client, owner, "business").status_code == 200
    assert _member_login(client).status_code == 200


@pytest.mark.parametrize("plan", ["business", "enterprise", "lifetime"])
def test_members_keep_working_on_team_plans(client, seed_owner, seed_member, plan):
    seed_member(seed_owner(plan=plan))
    assert _member_login(client).status_code == 200


# ── الكوبونات غير من Pro وفوق: الإنشاء يترفض، والقديمة ما تتطبقش فالـ checkout ──
COUPON = {"type": "percent", "value": 10, "active": True}


@pytest.mark.parametrize("plan,allowed", [("starter", False), ("free", False), ("pro", True), ("business", True)])
def test_coupons_follow_the_plan(client, db, seed_owner, plan, allowed):
    owner = seed_owner(plan=plan)
    uid = owner["uid"]
    r = client.post("/api/coupons/create", headers=owner["headers"], json={"code": "NEW10", **COUPON})
    assert (r.status_code == 200) is allowed and bool(db.get(f"data/{uid}/coupons/NEW10")) is allowed
    db.set(f"data/{uid}/coupons/OLD10", COUPON)
    r = client.get("/api/coupons/validate", query_string={"userId": uid, "code": "OLD10", "subtotal": "1000"})
    assert (r.status_code == 200) is allowed
    assert client.get("/api/coupons/list", headers=owner["headers"]).status_code == 200  # يشوف ويمسح
    assert app_discount(uid, "OLD10") == (100.0 if allowed else 0.0)


def app_discount(uid, code):
    from services.coupons import _validate_and_apply_coupon
    return _validate_and_apply_coupon(uid, code, 1000.0)[0]


# ── تصدير الطلبات (Excel = CSV UTF-8 بـ BOM، فاصل ;) من Starter وفوق ──
def _export(client, owner, **q):
    return client.get("/api/exportOrders", query_string=q, headers=owner["headers"])


def _seed_orders(db, uid, rows):
    for i, o in enumerate(rows):
        db.set(f"data/{uid}/orders/ORD-{i}", {"id": f"ORD-{i}", "status": "Pending", **o})


def test_export_orders_csv(client, db, seed_owner):
    owner = seed_owner(plan="starter")
    now = _now()
    _seed_orders(db, owner["uid"], [
        {"name": "أمينة; \"B\"", "phone": "0555123456", "city": "Alger", "product": "Sac", "qty": 2,
         "total": 5400, "createdAt": now - DAY, "updatedAt": now - DAY},
        {"name": "=HYPERLINK(\"x\")", "phone": "0666", "createdAt": now - 2 * DAY, "updatedAt": now},
        {"name": "قديم", "createdAt": now - 200 * DAY, "updatedAt": now},
    ])
    fakes.READS.clear()
    r = _export(client, owner)
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"] and ".csv" in r.headers["Content-Disposition"]
    raw = r.get_data()
    assert raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines[0].split(";")[:3] == ["ID", "Date", "Nom / الاسم"] and len(lines) == 3  # 90 يوم افتراضياً
    assert lines[1].startswith("ORD-0;") and '"أمينة; ""B"""' in lines[1] and ";0555123456;" in lines[1]
    assert "'=HYPERLINK" in lines[2]                    # CSV injection
    assert ("get", f"/data/{owner['uid']}/orders", {}) not in fakes.READS
    r = _export(client, owner, **{"from": now - 365 * DAY, "to": now})
    assert len(r.get_data().decode("utf-8-sig").splitlines()) == 4
    assert _export(client, owner, **{"from": "x"}).status_code == 400


def test_export_needs_the_plan_and_the_orders_permission(client, seed_owner, seed_member):
    assert _export(client, seed_owner(plan="free")).status_code == 403
    biz = seed_owner(username="biz", uid="3003", plan="business")
    member = seed_member(biz, perms={"products": True})
    assert _export(client, member).status_code == 403


def test_export_button_shows_only_with_the_feature():
    assert 'data-on-click="exportOrders()"' in DASH and 'id="exportOrdersBtn"' in DASH
    fn = DASH[DASH.index("async function exportOrders("):]
    assert "/exportOrders" in fn[:fn.index("\n}\n")] and "Authorization" in fn[:fn.index("\n}\n")]
    assert 'planHas("export")' in DASH


# ── Free: بلا متجر عام وبلا تتبع (فالسيرفر)؛ الطلبات اليدوية من اللوحة تبقى ──
ORDER_DATA = {"name": "Amina", "phone": "0555123456", "product": "Sac", "qty": 1,
              "city": "Alger", "deliveryType": "home", "address": "12 Rue"}


def _store_calls(client, uid):
    q = {"userId": uid}
    return {
        "products": client.get("/api/getStoreProducts", query_string=q).status_code,
        "cities": client.get("/api/getStoreCities", query_string=q).status_code,
        "track": client.get("/api/trackOrder", query_string={**q, "phone": "0555123456"}).status_code,
        "ratings": client.get("/api/getProductRatings", query_string={**q, "product": "Sac"}).status_code,
        "order": client.post("/api/addOrder", json={"userId": uid, "data": ORDER_DATA}).status_code,
    }


@pytest.fixture
def store_owner(db, seed_owner):
    def make(plan, **extra):
        owner = seed_owner(plan=plan, **extra)
        db.set(f"data/{owner['uid']}/products/Sac", {"name": "Sac", "sell": 2500, "init": 10})
        db.set(f"data/{owner['uid']}/cities/Alger", {"name": "Alger", "custShip": 400})
        return owner
    return make


def test_free_plan_has_no_public_store_or_tracking(client, db, store_owner):
    owner = store_owner("free")
    assert set(_store_calls(client, owner["uid"]).values()) == {403}
    assert db.get(f"data/{owner['uid']}/orders") is None
    assert client.get("/api/getStoreSettings", query_string={"userId": owner["uid"]}).status_code == 200


def test_expired_subscription_closes_the_store(client, store_owner):
    owner = store_owner("starter", plan_expires_at=_now() - 5 * DAY)
    assert _store_calls(client, owner["uid"])["products"] == 403


@pytest.mark.parametrize("plan", ["starter", "pro", "business"])
def test_paid_plans_keep_the_store(client, store_owner, plan):
    owner = store_owner(plan)
    assert set(_store_calls(client, owner["uid"]).values()) == {200}


def test_free_merchant_still_adds_orders_from_the_dashboard(client, db, store_owner, seed_member):
    owner = store_owner("free")
    r = client.post("/api/addOrder", headers=owner["headers"], json={"userId": owner["uid"], "data": ORDER_DATA})
    assert r.status_code == 200 and len(db.get(f"data/{owner['uid']}/orders")) == 1
    other = store_owner("free", username="other", uid="4004")
    r = client.post("/api/addOrder", headers=other["headers"], json={"userId": owner["uid"], "data": ORDER_DATA})
    assert r.status_code == 403
    assert 'apiPost("/addOrder", {userId:uid(), data:data}, true)' in DASH


def test_shop_page_shows_store_unavailable():
    shop = page_source("shop.html")
    fn = shop[shop.index("async function loadShopData("):]
    assert "store_unavailable" in fn[:fn.index("\n}\n")]
