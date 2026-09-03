# -*- coding: utf-8 -*-
"""
موديول تواصل التجار مع فريق الدعم — تذكرة + إيميل فوري.
قاعدة البيانات: support_tickets/{ticketId}  (عام، مو تحت data/{uid}/)

متغيرات بيئة مطلوبة (Render → Environment):
  SUPPORT_EMAIL_TO   = الإيميل يلي بدك توصلك فيه التذاكر
  SENDGRID_API_KEY    = مفتاح SendGrid (الطريقة المفضّلة — أسهل وأثبت على Render)
  SENDGRID_FROM_EMAIL = إيميل مُرسِل مُفعّل ("verified sender") بحساب SendGrid

  -- أو كبديل (SMTP مباشر، أقل موثوقية على استضافات سحابية) --
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
"""
import os
import time
import logging
import requests
from flask import Blueprint, request
from app import require_auth, _fb_push, _fb_get, _fb_patch, ok_json, err_json

support_bp = Blueprint("support", __name__)

SUPPORT_EMAIL_TO = os.environ.get("SUPPORT_EMAIL_TO", "").strip()
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "").strip()
SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "").strip()

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()

TICKET_TYPES = {"bug": "🐛 مشكلة تقنية", "suggestion": "💡 اقتراح", "feature_request": "✨ طلب ميزة", "other": "📋 أخرى"}


def _send_via_sendgrid(subject, html_body):
    if not (SENDGRID_API_KEY and SENDGRID_FROM_EMAIL and SUPPORT_EMAIL_TO):
        return False
    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": SUPPORT_EMAIL_TO}]}],
                "from": {"email": SENDGRID_FROM_EMAIL, "name": "OrderFlow Support"},
                "subject": subject,
                "content": [{"type": "text/html", "value": html_body}],
            },
            timeout=15,
        )
        return r.status_code in (200, 202)
    except Exception as e:
        logging.error(f"SendGrid error: {e}")
        return False


def _send_via_smtp(subject, html_body):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and SUPPORT_EMAIL_TO):
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = SUPPORT_EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [SUPPORT_EMAIL_TO], msg.as_string())
        return True
    except Exception as e:
        logging.error(f"SMTP error: {e}")
        return False


def _send_support_email(ticket, ticket_id):
    subject = f"[OrderFlow Support] {TICKET_TYPES.get(ticket['type'], ticket['type'])} — {ticket['username']}"
    html = f"""
    <div style="font-family:Arial;padding:16px">
      <h3>تذكرة دعم جديدة #{ticket_id}</h3>
      <p><strong>التاجر:</strong> {ticket['username']} (UID: {ticket['uid']})</p>
      <p><strong>النوع:</strong> {TICKET_TYPES.get(ticket['type'], ticket['type'])}</p>
      <p><strong>الرسالة:</strong></p>
      <p style="background:#f4f4f4;padding:12px;border-radius:8px">{ticket['message']}</p>
      <p style="color:#888;font-size:12px">{ticket['created_at']}</p>
    </div>"""
    if _send_via_sendgrid(subject, html):
        return True
    return _send_via_smtp(subject, html)


@support_bp.route("/api/support/submit", methods=["POST"])
@require_auth
def submit_support_ticket():
    uid = request.auth_uid
    body = request.get_json(silent=True) or {}
    ttype = str(body.get("type") or "other").strip()
    if ttype not in TICKET_TYPES:
        ttype = "other"
    message = str(body.get("message") or "").strip()[:2000]
    if not message:
        return err_json("اكتب رسالتك أولاً")

    ticket = {
        "uid": uid,
        "username": request.auth_username or "—",
        "type": ttype,
        "message": message,
        "status": "open",
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    ticket_id = _fb_push("support_tickets", ticket)
    email_ok = _send_support_email(ticket, ticket_id)
    if not email_ok:
        logging.warning(f"⚠️ support ticket {ticket_id} created but email failed to send")
    return ok_json({"ticketId": ticket_id, "emailSent": email_ok})


@support_bp.route("/api/support/myTickets", methods=["GET"])
@require_auth
def my_tickets():
    uid = request.auth_uid
    raw = _fb_get("support_tickets") or {}
    items = []
    if isinstance(raw, dict):
        for tid, t in raw.items():
            if isinstance(t, dict) and str(t.get("uid")) == str(uid):
                items.append({**t, "id": tid})
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return ok_json(items)