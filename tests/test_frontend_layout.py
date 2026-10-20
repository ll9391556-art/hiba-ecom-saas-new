# -*- coding: utf-8 -*-
"""Phase 4 / F1-F5 — بنية الواجهة بلا build: CSS وJS فملفات ثابتة، تتحمّل بنفس الترتيب."""
import re

from tests.frontend import STATIC

# ترتيب التحميل مهم: سكريبتات عادية (classic) تتشارك نفس النطاق العام، وكل ملف ينفّذ بالترتيب
DASHBOARD_SCRIPTS = ["core.js", "auth.js", "api.js", "dashboard.js", "orders.js", "catalog.js", "store.js",
                     "messaging.js", "settings.js", "ui.js", "shop.js", "theme.js", "main.js"]


def _local_scripts(page):
    html = (STATIC / page).read_text(encoding="utf-8")
    return re.findall(r'<script src="/static/js/([^"]+)"></script>', html), html


def test_index_loads_css_and_js_files(client):
    scripts, html = _local_scripts("index.html")
    assert '<link rel="stylesheet" href="/static/css/app.css"/>' in html
    assert "<style>" not in html
    assert re.search(r"<script>(?!\s*</script>)", html) is None  # ما كاين حتى سكريبت داخلي
    assert scripts == DASHBOARD_SCRIPTS
    for path, mime in [("/static/css/app.css", "text/css")] + [(f"/static/js/{s}", "text/javascript") for s in scripts]:
        r = client.get(path)
        assert r.status_code == 200 and r.mimetype == mime, path
