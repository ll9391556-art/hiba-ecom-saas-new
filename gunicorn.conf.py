# -*- coding: utf-8 -*-
"""إعدادات gunicorn — يتقرا أوتوماتيكياً من مجلد التشغيل (Dockerfile: CMD ["gunicorn", "app:app"]).

الذاكرة: كل worker عملية منفصلة كتحمّل Flask + firebase-admin + google-genai (+ خيوط البوت)،
تقريباً 120-180 MB. 4 workers كانو يفوتو 512 MB (Render Free/Starter) → OOM وإعادة تشغيل.
2 workers × 8 خيوط: الشغل أغلبه انتظار شبكة (Firebase/Gemini/Meta)، فالخيوط تكفي.
بلا preload: Firebase يتهيّأ فكل worker (اتصالات HTTP ما تتشاركش بين عمليات fork).
"""
import logging
import os
import threading
import time
import urllib.request

bind         = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers      = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads      = int(os.environ.get("GUNICORN_THREADS", "8"))
worker_class = "gthread"
timeout      = 120

# keepalive: ping وحيد من master gunicorn (ماشي من كل worker)، باش Render Free ما ينعسش
# بعد 15 دقيقة بلا زيارات. غير إذا RENDER_EXTERNAL_URL مضبوط (Render يضبطو وحدو) —
# بلا fallback لـ localhost (كان بالبورت الغلط).
_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
KEEPALIVE_URL = f"{_EXTERNAL_URL}/healthz" if _EXTERNAL_URL else ""
KEEPALIVE_EVERY_S = 600


def _keepalive():
    time.sleep(60)
    while True:
        try:
            with urllib.request.urlopen(KEEPALIVE_URL, timeout=10) as r:
                logging.getLogger("gunicorn.error").info(f"💓 Keepalive {r.status}")
        except Exception as e:
            logging.getLogger("gunicorn.error").warning(f"Keepalive failed: {type(e).__name__}")
        time.sleep(KEEPALIVE_EVERY_S)


def when_ready(server):
    if KEEPALIVE_URL:
        threading.Thread(target=_keepalive, name="keepalive", daemon=True).start()
