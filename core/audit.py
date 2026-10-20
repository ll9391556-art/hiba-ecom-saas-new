# -*- coding: utf-8 -*-
"""سجل عمليات الفريق data/{uid}/auditLog. كان فـ features/assistant_api.py، وapp.py كان
يستوردو من داخل الدوال (استيراد دائري) — دابا core ما يعتمدش على app ولا features."""
import logging
import time

from core.db import _fb_push

# ── تسجيل تدقيق (Audit Log) — دالة تُستدعى من نقاط حساسة بالكود الأصلي ──
def log_audit_entry(uid, actor, action, details=""):
    try:
        _fb_push(f"data/{uid}/auditLog", {
            "actor": actor, "action": action, "details": details,
            "timestamp": time.time(), "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        logging.error(f"log_audit_entry: {e}")
