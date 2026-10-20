# -*- coding: utf-8 -*-
"""Phase 4 / F1-F5 — بنية الواجهة بلا build: CSS وJS فملفات ثابتة، تتحمّل بنفس الترتيب."""
import re

from tests.frontend import STATIC

# ترتيب التحميل مهم: سكريبتات عادية (classic) تتشارك نفس النطاق العام، وكل ملف ينفّذ بالترتيب
DASHBOARD_SCRIPTS = ["core.js", "auth.js", "api.js", "dashboard.js", "orders.js", "catalog.js", "store.js",
                     "messaging.js", "settings.js", "ui.js", "theme.js", "main.js"]
SHOP_SCRIPTS = ["core.js", "api.js", "shop.js", "theme.js", "shop-main.js"]


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


def test_storefront_is_its_own_page(client):
    """F3 — /?store=<uid> كيرجّع shop.html (بلا كود ولا عناصر اللوحة)، و / كيرجّع اللوحة."""
    shop = client.get("/?store=1001").get_data(as_text=True)
    dash = client.get("/").get_data(as_text=True)
    assert 'id="shopApp"' in shop and 'id="loginPage"' not in shop and 'id="sidebar"' not in shop
    assert 'id="shopApp"' not in dash and 'id="loginPage"' in dash
    assert client.get("/?store=").get_data(as_text=True) == dash   # store فارغ = اللوحة، كيما قبل
    scripts, html = _local_scripts("shop.html")
    assert scripts == SHOP_SCRIPTS
    assert '<link rel="stylesheet" href="/static/css/app.css"/>' in html
    assert '<script defer src="/static/pixel-loader.js"></script>' in html
    for s in scripts:
        assert client.get(f"/static/js/{s}").status_code == 200


def _unguarded_missing_ids(page, scripts):
    """getElementById("x").prop بلا فحص null على id ما كاينش فالصفحة (ولا يتولّد فـ JS) → TypeError."""
    html = (STATIC / page).read_text(encoding="utf-8")
    js = {s: (STATIC / "js" / s).read_text(encoding="utf-8") for s in scripts}
    known = set(re.findall(r'id="([^"]+)"', html + "".join(js.values())))
    known |= set(re.findall(r"\.id\s*=\s*\"([^\"]+)\"", "".join(js.values())))
    bad = []
    for name, src in js.items():
        for line in src.split("\n"):
            for m in re.finditer(r'getElementById\("([^"]+)"\)\.', line):
                guarded = re.search(r'getElementById\("%s"\)\s*&&' % re.escape(m.group(1)), line[:m.start()])
                if m.group(1) not in known and not guarded:
                    bad.append(f"{name}: {m.group(1)}")
    return sorted(set(bad))


def test_dashboard_scripts_only_touch_dashboard_elements():
    assert _unguarded_missing_ids("index.html", DASHBOARD_SCRIPTS) == []


def test_shop_scripts_only_touch_shop_elements():
    assert _unguarded_missing_ids("shop.html", SHOP_SCRIPTS) == []


def test_feature_pages_use_shared_helpers():
    """F4 — صفحات features/ كتستعمل core.js + api.js بدل نسخها الخاصة."""
    for page in sorted((STATIC / "features").glob("*.html")):
        scripts, html = _local_scripts(f"features/{page.name}")
        assert scripts[:2] == ["core.js", "api.js"], page.name
        inline = "".join(re.findall(r"<script>([\s\S]*?)</script>", html))
        for dup in ("var API_URL", "var authToken", "function apiGet", "function apiPost", "function esc("):
            assert dup not in inline, f"{page.name} still defines {dup}"
