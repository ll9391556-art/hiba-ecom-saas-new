# -*- coding: utf-8 -*-
"""طبقة Firebase RTDB: قراءة/كتابة/استعلام مع إعادة محاولة على الأخطاء المؤقتة.
منقول من app.py بلا تغيير (Phase 4 / A2). app.py يعاود يصدّر نفس الأسماء."""
import logging
from time import sleep

import requests
from firebase_admin import db

# ── إعادة المحاولة (INFO-004) ──
# قبل: _firebase_ref كان يعاود db.reference() — وهي ما تتصلش بالشبكة أصلاً، فالفشل الحقيقي
# (.get/.set) ما كانش يتعاود أبداً. دابا: محاولة ثانية وحدة بعد 0.5 ثانية، غير على الأخطاء
# المؤقتة (انقطاع، timeout، 5xx). push ما يتعاودش: ماشي idempotent (نسخة مكررة).
_FB_TRANSIENT_ERRORS = {"UnavailableError", "InternalError", "DeadlineExceededError", "UnknownError"}


def _fb_is_transient(e):
    return (isinstance(e, (requests.ConnectionError, requests.Timeout))
            or type(e).__name__ in _FB_TRANSIENT_ERRORS)


def _fb_call(fn):
    try:
        return fn()
    except Exception as e:
        if not _fb_is_transient(e):
            raise
        logging.warning(f"Firebase transient error ({type(e).__name__}) — retrying once")
        sleep(0.5)
        return fn()


def _fb_get(path):
    try:
        return _fb_call(lambda: _firebase_ref(path).get())
    except Exception as e:
        logging.error(f"_fb_get({path}): {e}"); return None


def _fb_query(path, order_by, *, equal_to=None, start_at=None, end_at=None, limit_last=None):
    """استعلام RTDB بدل تنزيل العقدة كاملة. order_by: اسم child (لازم يكون فـ ".indexOn" ف
    database.rules.json، وإلا Firebase يرفض) أو "$key". يرجّع dict مرتّب ({} إذا ما كاين والو)،
    أو None عند الخطأ — باش المستدعي يفرّق بين "فارغ" و"فشل"."""
    def run():
        ref = _firebase_ref(path)
        q = ref.order_by_key() if order_by == "$key" else ref.order_by_child(order_by)
        if equal_to is not None: q = q.equal_to(equal_to)
        if start_at is not None: q = q.start_at(start_at)
        if end_at is not None:   q = q.end_at(end_at)
        if limit_last:           q = q.limit_to_last(int(limit_last))
        return q.get()
    try:
        return _fb_call(run) or {}
    except Exception as e:
        logging.error(f"_fb_query({path}, {order_by}): {e}"); return None


def _fb_keys(path):
    """مفاتيح الأبناء فقط (REST ?shallow=true) بلا تنزيل المحتوى. None عند الخطأ."""
    try:
        data = _fb_call(lambda: _firebase_ref(path).get(shallow=True))
    except Exception as e:
        logging.error(f"_fb_keys({path}): {e}"); return None
    return list(data.keys()) if isinstance(data, dict) else []


def _fb_put(path, data):
    try:
        _fb_call(lambda: _firebase_ref(path).set(data))
        return True
    except Exception as e:
        logging.error(f"_fb_put({path}): {e}"); return False


def _fb_patch(path, data):
    try:
        _fb_call(lambda: _firebase_ref(path).update(data))
        return True
    except Exception as e:
        logging.error(f"_fb_patch({path}): {e}"); return False


def _fb_delete(path):
    try:
        _fb_call(lambda: _firebase_ref(path).delete())
        return True
    except Exception as e:
        logging.error(f"_fb_delete({path}): {e}"); return False


def _fb_push(path, data):
    try:
        new_ref = _firebase_ref(path).push(data)
        return new_ref.key
    except Exception as e:
        logging.error(f"_fb_push({path}): {e}"); return None


def _fb_list(path):
    data = _fb_get(path)
    if not data or not isinstance(data, dict): return []
    return list(reversed(list(data.values())))


def _firebase_ref(path):
    # db.reference() محلي (ما يتصلش بالشبكة) — يرمي غير على مسار غير صالح، فما كاينش علاش نعاودو
    return db.reference(path)
