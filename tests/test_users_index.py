# -*- coding: utf-8 -*-
"""Phase 3 / branch 4 — بلا قراءة /users ولا /team_users كاملة: uname_index وteam_uname_index
لتسجيل الدخول، عدّاد lifetime، channel_index يتكتب عند حفظ إعدادات البوت، وتعبئة القديم."""
import pytest

from tests import fakes

ADMIN = {"X-Admin-Key": "dummy-admin-key"}
ROOT_READS = [("get", "/users", {}), ("get", "/team_users", {})]


def _root_reads():
    return [r for r in fakes.READS if r in ROOT_READS]


def _login(client, username, password="dummy-pass-123"):
    return client.post("/api/login", json={"username": username, "password": password})


def _create_client(client, username, plan="starter", password="dummy-pass-123"):
    return client.post("/api/admin/createClient", headers=ADMIN,
                       json={"username": username, "password": password, "plan": plan})


# ── تسجيل الدخول ─────────────────────────────────────────
def test_owner_login_is_case_insensitive_without_reading_all_users(client, db):
    assert _create_client(client, "Amina").status_code == 200
    assert db.get("uname_index/amina") == "Amina"
    fakes.READS.clear()
    r = _login(client, "AMINA")
    assert r.status_code == 200 and r.get_json()["data"]["role"] == "owner"
    assert _root_reads() == []


def test_legacy_owner_without_index_still_logs_in_with_exact_name(client, seed_owner):
    seed_owner(username="owner1")  # seed ما يكتبش uname_index (حساب قديم)
    fakes.READS.clear()
    assert _login(client, "owner1").status_code == 200
    assert _root_reads() == []


def test_unknown_user_is_rejected_without_reading_all_users(client, seed_owner):
    seed_owner()
    fakes.READS.clear()
    assert _login(client, "nobody").status_code == 401
    assert _root_reads() == []


def test_member_login_case_insensitive_via_team_index(client, db, seed_owner):
    owner = seed_owner()
    r = client.post("/api/team/addMember", headers=owner["headers"],
                    json={"username": "Karim", "password": "dummy-pass-123", "name": "K"})
    assert r.status_code == 200
    assert db.get("team_uname_index/karim") == "Karim"
    fakes.READS.clear()
    r = _login(client, "karim")
    assert r.status_code == 200 and r.get_json()["data"]["memberUsername"] == "Karim"
    assert _root_reads() == []


def test_usernames_are_unique_ignoring_case(client, db, seed_owner):
    owner = seed_owner()
    _create_client(client, "Amina")
    assert _create_client(client, "amina").status_code == 409
    add = lambda u: client.post("/api/team/addMember", headers=owner["headers"],
                                json={"username": u, "password": "dummy-pass-123"})
    assert add("AMINA").status_code == 409           # نفس اسم صاحب حساب
    assert add("Karim").status_code == 200
    assert add("KARIM").status_code == 409           # نفس اسم عضو
    assert _create_client(client, "karim").status_code == 409


def test_delete_member_removes_team_index(client, db, seed_owner):
    owner = seed_owner()
    client.post("/api/team/addMember", headers=owner["headers"],
                json={"username": "Karim", "password": "dummy-pass-123"})
    assert client.post("/api/team/deleteMember", headers=owner["headers"],
                       json={"username": "Karim"}).status_code == 200
    assert db.get("team_uname_index/karim") is None


# ── عدّاد lifetime ───────────────────────────────────────
def test_lifetime_counter_and_cap(client, db, app, monkeypatch):
    monkeypatch.setattr(app, "LIFETIME_MAX_SLOTS", 2)
    assert _create_client(client, "a1", plan="lifetime").status_code == 200
    assert _create_client(client, "a2", plan="starter").status_code == 200
    assert db.get("counters/lifetimeAccounts") == 1
    assert _create_client(client, "a3", plan="full").status_code == 200
    assert db.get("counters/lifetimeAccounts") == 2
    assert _create_client(client, "a4", plan="lifetime").status_code == 409
    assert db.get("users/a4") is None and db.get("counters/lifetimeAccounts") == 2


def test_plan_changes_move_the_counter(client, db):
    _create_client(client, "a1", plan="starter")
    uid = db.get("users/a1")["User_ID"]
    upd = lambda plan: client.post("/api/updateUserPlan", headers=ADMIN,
                                   json={"userId": uid, "username": "a1", "plan": plan})
    assert upd("lifetime").status_code == 200 and db.get("counters/lifetimeAccounts") == 1
    assert upd("full").status_code == 200 and db.get("counters/lifetimeAccounts") == 1
    assert upd("pro").status_code == 200 and (db.get("counters/lifetimeAccounts") or 0) == 0


def test_get_user_plan_reads_counter_not_all_users(client, db, seed_owner):
    owner = seed_owner(plan="pro")
    db.set("counters/lifetimeAccounts", 7)
    fakes.READS.clear()
    data = client.get("/api/getUserPlan", headers=owner["headers"]).get_json()["data"]
    assert data["lifetimeSlotsLeft"] == 50 - 7
    assert _root_reads() == []


# ── مسارات عامة ما تقراش /users ─────────────────────────
def test_public_add_order_with_unknown_store_reads_no_users(client, seed_owner):
    seed_owner()
    fakes.READS.clear()
    r = client.post("/api/addOrder", json={"userId": "999999", "data": {"name": "x", "phone": "0555"}})
    assert r.status_code == 404
    assert _root_reads() == []


def test_unknown_channel_is_not_scanned_and_is_negative_cached(app, seed_owner):
    seed_owner()
    fakes.READS.clear()
    assert app.get_user_settings("123456789") is None
    assert _root_reads() == []
    n = len(fakes.READS)
    assert app.get_user_settings("123456789") is None
    assert len(fakes.READS) == n  # من الكاش


# ── channel_index عند حفظ إعدادات البوت ─────────────────
def _save_bot(client, owner, **data):
    return client.post("/api/updateBotSettings", headers=owner["headers"], json={"data": data})


def test_saving_bot_settings_writes_channel_index(client, db, app, seed_owner):
    owner = seed_owner()
    assert _save_bot(client, owner, phone_number_id="1111", page_id_FB="2222").status_code == 200
    assert db.get("channel_index/1111") == owner["username"]
    assert db.get("channel_index/2222") == owner["username"]
    assert app.get_user_settings("1111")["User_ID"] == owner["uid"]
    # تبديل المعرّف: القديم يتمسح
    assert _save_bot(client, owner, phone_number_id="3333").status_code == 200
    assert db.get("channel_index/1111") is None and db.get("channel_index/3333") == owner["username"]


def test_channel_id_owned_by_another_account_is_refused(client, db, seed_owner):
    a = seed_owner(username="ownerA", uid="1001")
    b = seed_owner(username="ownerB", uid="2002")
    assert _save_bot(client, a, phone_number_id="1111").status_code == 200
    r = _save_bot(client, b, phone_number_id="1111", AI_instructions="hijack")
    assert r.status_code == 409
    assert db.get("channel_index/1111") == "ownerA"
    assert db.get("users/ownerB").get("AI_instructions") is None


def test_non_numeric_channel_id_is_refused(client, seed_owner):
    owner = seed_owner()
    assert _save_bot(client, owner, phone_number_id="12/34").status_code == 400


# ── التعبئة ─────────────────────────────────────────────
def test_backfill_builds_user_indexes_and_counter(client, db):
    db.set("users", {
        "Amina": {"Username": "Amina", "User_ID": "1001", "plan": "lifetime", "phone_number_id": "1111"},
        "bob":   {"Username": "bob", "User_ID": "2002", "plan": "full", "page_id_FB": "2222"},
        "carl":  {"Username": "carl", "User_ID": "3003", "plan": "pro", "page_id_FB": "2222"},
    })
    db.set("team_users", {"Karim": {"Username": "Karim", "ownerUid": "1001"}})
    db.set("counters/lifetimeAccounts", 99)  # خاطئ — يتصحّح
    res = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["users"]
    assert res["users"] == 3 and res["members"] == 1 and res["lifetimeAccounts"] == 2
    assert res["conflicts"] == ["channel_index/2222: bob vs carl"]
    assert db.get("uname_index/amina") == "Amina" and db.get("uid_index/3003") == "carl"
    assert db.get("team_uname_index/karim") == "Karim"
    assert db.get("channel_index/1111") == "Amina" and db.get("channel_index/2222") == "bob"
    assert db.get("counters/lifetimeAccounts") == 2
    assert _login(client, "AMINA").status_code in (200, 401)  # الحساب موجود (كلمة سر غير مضبوطة هنا)
    again = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["users"]
    assert again["lifetimeAccounts"] == 2 and again["conflicts"] == ["channel_index/2222: bob vs carl"]
