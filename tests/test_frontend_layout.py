# -*- coding: utf-8 -*-
"""Phase 4 / F1-F5 — بنية الواجهة بلا build: CSS وJS فملفات ثابتة، تتحمّل بنفس الترتيب."""
import re

from tests.frontend import STATIC

# ترتيب التحميل مهم: سكريبتات عادية (classic) تتشارك نفس النطاق العام، وكل ملف ينفّذ بالترتيب
DASHBOARD_SCRIPTS = ["core.js", "actions.js", "auth.js", "api.js", "dashboard.js", "orders.js", "catalog.js", "store.js",
                     "messaging.js", "settings.js", "ui.js", "theme.js", "main.js"]
SHOP_SCRIPTS = ["core.js", "actions.js", "api.js", "shop.js", "theme.js", "shop-main.js"]


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


# ── F5: بلا handlers inline؛ data-on-<event> + جدول ACTIONS ──
_EVENT_ATTR = re.compile(r'\bdata-on-(click|change|input|keydown|error)="([^"]*)"')
_INLINE_ATTR = re.compile(r'\bon(click|change|input|keydown|error|keyup|submit|load|focus|blur|mouseover)=\\?"')
_TABLE_KEY = re.compile(r'^\s*("(?:[^"\\]|\\.)*"): function\(event\)\{', re.M)


def _code_lines(text):
    return [l for l in text.split("\n") if not l.lstrip().startswith("//")]


def test_no_inline_event_handlers_left():
    """onclick="..." وأمثالها ممنوعين (CSP مستقبلاً) — إلا زر الطباعة داخل نافذة بون الطلب
    (وثيقة منفصلة بلا delegation)."""
    hits = []
    for path in sorted(STATIC.rglob("*.html")) + sorted(STATIC.rglob("*.js")):
        for i, line in enumerate(_code_lines(path.read_text(encoding="utf-8")), 1):
            if _INLINE_ATTR.search(line) and 'onclick=\\"window.print()\\"' not in line:
                hits.append(f"{path.relative_to(STATIC)}:{i}")
    assert hits == []


def _used_keys(text, is_js):
    keys = set()
    for line in _code_lines(text):
        for m in _EVENT_ATTR.finditer(line):
            raw = m.group(2)
            keys.add(raw.replace("\\'", "'") if is_js else raw)
    return keys


def _table_keys(text):
    import json
    return {json.loads(k) for k in _TABLE_KEY.findall(text)}


def test_every_handler_has_an_action():
    table = _table_keys((STATIC / "js" / "actions.js").read_text(encoding="utf-8"))
    used = set()
    for page in ("index.html", "shop.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        markup = re.sub(r"<script>[\s\S]*?</script>", "", html)
        used |= _used_keys(markup, False)
    for js in sorted((STATIC / "js").glob("*.js")):
        used |= _used_keys(js.read_text(encoding="utf-8"), True)
    assert used and sorted(used - table) == []
    for page in sorted((STATIC / "features").glob("*.html")):
        html = page.read_text(encoding="utf-8")
        inline = "".join(re.findall(r"<script>([\s\S]*?)</script>", html))
        need = _used_keys(re.sub(r"<script>[\s\S]*?</script>", "", html), False) | _used_keys(inline, True)
        assert sorted(need - _table_keys(inline)) == [], page.name


def test_pages_load_actions_after_core():
    for page, scripts in (("index.html", DASHBOARD_SCRIPTS), ("shop.html", SHOP_SCRIPTS)):
        got, _ = _local_scripts(page)
        assert got[:2] == ["core.js", "actions.js"], page
    core = (STATIC / "js" / "core.js").read_text(encoding="utf-8")
    assert "function registerActions(" in core and 'document.addEventListener(type' in core
