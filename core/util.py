# -*- coding: utf-8 -*-
"""أدوات صغيرة بلا اعتماديات (أرقام آمنة). منقول من app.py بلا تغيير (Phase 4 / A3)."""

def _safe_int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _cents(v):
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return 0




def _mask_id(v):
    """للسجلات فقط: آخر 4 أحرف من معرّف الزبون (فواتساب = رقم هاتفه)."""
    s = str(v or "")
    return ("…" + s[-4:]) if len(s) > 4 else "…"
