# -*- coding: utf-8 -*-
"""SEC-016 — نص تذكرة الدعم ما يتحقنش كـ HTML فالإيميل."""
import pytest

PAYLOAD = '<a href="https://evil.test">اضغط</a><script>x</script>'


@pytest.fixture
def sent(monkeypatch):
    from features import support_api
    out = []
    monkeypatch.setattr(support_api, "_send_via_sendgrid", lambda subject, html: out.append(html) or True)
    return out


def test_support_email_escapes_message_and_username(client, db, seed_owner, sent):
    owner = seed_owner(username="o<b>wner")
    r = client.post("/api/support/submit", json={"type": "bug", "message": PAYLOAD}, headers=owner["headers"])
    assert r.status_code == 200
    html = sent[0]
    assert "<script>" not in html and '<a href="https://evil.test">' not in html
    assert "&lt;script&gt;" in html
    assert "o<b>wner" not in html and "o&lt;b&gt;wner" in html
    tickets = db.get("support_tickets")
    assert list(tickets.values())[0]["message"] == PAYLOAD  # التذكرة تتخزّن بالنص الأصلي
