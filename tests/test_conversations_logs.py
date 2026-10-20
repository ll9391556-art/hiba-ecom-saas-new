# -*- coding: utf-8 -*-
"""Phase 3 / branch 6 — المحادثات والرسائل وسجل البوت وتذاكر الدعم وسجل الفريق: صفحات
واستعلامات بدل تنزيل العقدة كاملة، والواجهة تجيب غير الجديد وتوقف كي يكون التبويب مخفي."""
import json
import pathlib

from tests.frontend import dashboard_and_shop

import pytest

from tests import fakes

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = dashboard_and_shop()  # HTML + /static/js/* (Phase 4 / F1)
ADMIN = {"X-Admin-Key": "dummy-admin-key"}
T0 = 1_700_000_000.0  # ثواني (time.time) كيما _log_conversation


@pytest.fixture
def owner(seed_owner):
    return seed_owner()


def _full_get(path):
    return ("get", path, {}) in fakes.READS


# ── قائمة المحادثات ──────────────────────────────────────
def _seed_meta(db, uid, n):
    for i in range(n):
        db.set(f"conversations_meta/{uid}/S{i:03d}", {"lastTimestamp": T0 + i, "lastMessage": f"m{i}",
                                                       "platform": "wa", "name": f"N{i}"})


def _convs(client, owner, **q):
    return client.get("/api/getConversations", query_string=q, headers=owner["headers"]).get_json()


def test_conversations_latest_page_newest_first(client, db, owner):
    uid = owner["uid"]
    _seed_meta(db, uid, 60)
    fakes.READS.clear()
    body = _convs(client, owner)
    assert [c["senderId"] for c in body["data"][:2]] == ["S059", "S058"] and len(body["data"]) == 50
    assert body["hasMore"] is True and "cursor" in body
    assert not _full_get(f"/conversations_meta/{uid}")


def test_conversations_older_page_and_since(client, db, owner, app, monkeypatch):
    uid = owner["uid"]
    _seed_meta(db, uid, 60)
    monkeypatch.setattr(app.time, "time", lambda: T0 + 100)
    first = _convs(client, owner)
    oldest = min(c["lastTimestamp"] for c in first["data"])
    older = _convs(client, owner, before=oldest)
    assert [c["senderId"] for c in older["data"]] == [f"S{i:03d}" for i in range(9, -1, -1)]
    assert older["hasMore"] is False
    monkeypatch.setattr(app.time, "time", lambda: T0 + 1000)
    app._log_conversation(uid, "S005", "in", "salam", "wa")
    poll = _convs(client, owner, since=first["cursor"])
    assert [c["senderId"] for c in poll["data"]] == ["S005"] and poll["data"][0]["lastMessage"] == "salam"


def test_log_conversation_does_not_read_meta(app, db, owner):
    uid = owner["uid"]
    fakes.READS.clear()
    app._log_conversation(uid, "S1", "in", "salam", "wa", page_id="P1")
    assert not any(r[1] == f"/conversations_meta/{uid}/S1" for r in fakes.READS)
    meta = db.get(f"conversations_meta/{uid}/S1")
    assert meta["lastMessage"] == "salam" and meta["pageId"] == "P1"


# ── رسائل محادثة ────────────────────────────────────────
def _seed_msgs(db, uid, sid, n):
    for i in range(n):
        db.set(f"conversations/{uid}/{sid}/-k{i:04d}", {"text": f"t{i}", "timestamp": T0 + i, "direction": "in"})


def _msgs(client, owner, **q):
    return client.get("/api/getConversationMessages", query_string={"senderId": "S1", **q},
                      headers=owner["headers"]).get_json()


def test_messages_latest_page_after_and_before(client, db, owner):
    uid = owner["uid"]
    _seed_msgs(db, uid, "S1", 130)
    fakes.READS.clear()
    page = _msgs(client, owner)
    ids = [m["id"] for m in page["data"]]
    assert ids[0] == "-k0030" and ids[-1] == "-k0129" and len(ids) == 100 and page["hasMore"] is True
    assert not _full_get(f"/conversations/{uid}/S1")
    older = _msgs(client, owner, before="-k0030")
    assert [m["id"] for m in older["data"]][-1] == "-k0029" and len(older["data"]) == 30
    assert older["hasMore"] is False
    db.set(f"conversations/{uid}/S1/-k0130", {"text": "new", "timestamp": T0 + 500, "direction": "out"})
    newer = _msgs(client, owner, after="-k0129")
    assert [m["id"] for m in newer["data"]] == ["-k0130"]
    assert _msgs(client, owner, after="-k0130")["data"] == []


# ── سجل البوت ───────────────────────────────────────────
def test_bot_logs_flat_and_limited(client, app, db, owner, monkeypatch):
    uid = owner["uid"]
    for i in range(5):
        monkeypatch.setattr(app.time, "time", lambda i=i: T0 + i)
        app.log_ai_message(f"SID{i % 2}", f"q{i}", f"a{i}", merchant_uid=uid)
    assert db.get(f"ai_logs/{uid}") is None
    assert len(db.get(f"bot_logs/{uid}")) == 5
    fakes.READS.clear()
    r = client.post("/api/saas", headers=owner["headers"], json={"action": "getBotLogs", "limit": 3})
    rows = r.get_json()["data"]
    assert [x["user_message"] for x in rows] == ["q4", "q3", "q2"]
    assert rows[0]["sender_id"] == "SID0" and rows[0]["id"]
    assert not _full_get(f"/bot_logs/{uid}") and not _full_get(f"/ai_logs/{uid}")


def test_backfill_migrates_legacy_nested_ai_logs(client, db, owner):
    uid = owner["uid"]
    db.set(f"ai_logs/{uid}", {"SID9": {"-a1": {"user_message": "old", "bot_reply": "r", "timestamp": T0}}})
    db.set(f"data/{uid}/storeSettings/name", "x")
    for _ in range(2):  # idempotent
        res = client.post("/api/admin/rebuildIndexes", headers=ADMIN).get_json()["data"]["botLogs"]
        assert res == {"merchants": 1, "copied": 1}
    rows = list(db.get(f"bot_logs/{uid}").values())
    assert rows == [{"user_message": "old", "bot_reply": "r", "timestamp": T0, "sender_id": "SID9"}]
    assert db.get(f"ai_logs/{uid}/SID9/-a1")  # القديم ما يتمسحش


def test_rules_index_bot_logs_timestamp():
    rules = json.loads((ROOT / "database.rules.json").read_text(encoding="utf-8"))["rules"]
    assert rules["bot_logs"]["$uid"][".indexOn"] == ["timestamp"]


# ── تذاكر الدعم ─────────────────────────────────────────
def test_my_tickets_queries_by_uid(client, db, owner):
    db.set("support_tickets", {"-t1": {"uid": owner["uid"], "message": "mine", "created_at": "2024-01-02"},
                               "-t2": {"uid": "9999", "message": "other", "created_at": "2024-01-03"}})
    fakes.READS.clear()
    rows = client.get("/api/support/myTickets", headers=owner["headers"]).get_json()["data"]
    assert [t["message"] for t in rows] == ["mine"]
    assert not _full_get("/support_tickets")


# ── المساعد: سجل الفريق، المحادثة، والملخص ───────────────
def test_assistant_reads_no_full_orders_or_audit_log(client, app, db, owner):
    uid = owner["uid"]
    db.set(f"data/{uid}/products/Sac", {"name": "Sac", "init": 4})
    db.set(f"data/{uid}/stats", {"total": 3, "confirmed": 2, "delivered": 1, "refused": 1, "profitCents": 12345,
                                  "sales": {"Sac": {"name": "Sac", "qty": 2}}})
    for i in range(30):
        db.set(f"data/{uid}/auditLog/-a{i:03d}", {"actor": "owner", "action": f"act{i}", "timestamp": T0 + i})
    fakes.READS.clear()
    summary = client.get("/api/assistant/weeklyReport", headers=owner["headers"]).get_json()["data"]["summary"]
    assert "إجمالي الطلبات: 3" in summary and "123.45" in summary and "act29" in summary and "act14" not in summary
    assert "Sac" in summary  # مخزون 4-2=2 ≤ 5
    log = client.get("/api/assistant/auditLog?limit=5", headers=owner["headers"]).get_json()["data"]
    assert [e["action"] for e in log] == ["act29", "act28", "act27", "act26", "act25"]
    assert not _full_get(f"/data/{uid}/orders") and not _full_get(f"/data/{uid}/auditLog")


def test_assistant_history_is_limited(client, db, owner):
    uid = owner["uid"]
    for i in range(50):
        db.set(f"admin_chats/{uid}/-c{i:03d}", {"role": "user", "content": f"c{i}", "timestamp": T0 + i})
    fakes.READS.clear()
    items = client.get("/api/assistant/history", headers=owner["headers"]).get_json()["data"]
    assert [x["content"] for x in items][0] == "c10" and items[-1]["content"] == "c49" and len(items) == 40
    assert not _full_get(f"/admin_chats/{uid}")


# ── الواجهة ─────────────────────────────────────────────
def _fn(name):
    start = INDEX.index(f"function {name}(")
    return INDEX[start:INDEX.index("\n}\n", start)].replace(" ", "")


def test_frontend_conversation_polls_are_incremental_and_pause_when_hidden():
    assert "since:CONV_CURSOR" in _fn("loadConversations")
    assert "after:CONV_LAST_KEY" in _fn("pollConversationMessages")
    for poller in ("startConvListPolling", "startConvPolling"):
        assert "document.hidden" in _fn(poller)
    assert "pollConversationMessages" in _fn("startConvPolling")
    # F5: الأزرار كتستعمل data-on-click (نفس نص الـ handler)
    assert 'data-on-click="loadOlderConversations()"' in INDEX and 'data-on-click="loadOlderMessages()"' in INDEX
