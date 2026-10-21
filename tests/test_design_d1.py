# -*- coding: utf-8 -*-
"""Design D1 — الأساس: ملف المتغيرات، الخط، الشعار، favicon، الأزرار، الحالات، الحقول.
المرجع: design/PLAN.md (المهمة 2) و design/Main.dc.html. التصميم فقط، بلا ما يتبدّل المنطق."""
import re

import pytest

from tests.frontend import ROOT, STATIC

TOKENS = STATIC / "css" / "tokens.css"
APP_CSS = STATIC / "css" / "app.css"
FEATURE_PAGES = sorted(p.relative_to(STATIC).as_posix() for p in (STATIC / "features").glob("*.html"))
STATIC_PAGES = ["index.html", "shop.html"] + FEATURE_PAGES
TEMPLATES = ["admin.html", "privacy.html", "oauth_success.html", "oauth_error.html"]
TOKENS_LINK = '<link rel="stylesheet" href="/static/css/tokens.css"/>'


def _read(path):
    return path.read_text(encoding="utf-8")


def _page(name):
    return _read(STATIC / name)


def _template(name):
    return _read(ROOT / "templates" / name)


def _all_pages():
    return [(n, _page(n)) for n in STATIC_PAGES] + [(f"templates/{n}", _template(n)) for n in TEMPLATES]


def _rules(css):
    """{selector: {prop: value}} — قواعد بسيطة (داخل @media تاني)، آخر قيمة تغلب."""
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    out = {}
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for d in body.split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls[k.strip().lower()] = v.strip()
        for s in sel.split(","):
            out.setdefault(s.strip(), {}).update(decls)
    return out


def _px(value):
    m = re.search(r"(\d+(?:\.\d+)?)px", value or "")
    return float(m.group(1)) if m else None


# ── 1. ملف المتغيرات ──
BRAND_TOKENS = {
    "--brand": "#3B2BFF", "--brand-dark": "#2A1DD1", "--brand-light": "#E6E3FF",
    "--volt": "#D4FF3A", "--volt-light": "#EFFFC2",
    "--ink": "#0B0B1F", "--text": "#2A2B3D", "--muted": "#5A5B70",
    "--flash": "#D9230F", "--bg": "#F4F4F8", "--line": "#DCDCE6",
}
STATUS_TOKENS = {
    "confirmed": ("#E6E3FF", "#2A1DD1"), "delivered": ("#EFFFC2", "#3A4A00"),
    "pending": ("#FFF1D6", "#7A4B00"), "refused": ("#FFE3DF", "#A3180A"),
}
DARK = ("#0b0b1f", "#0d1b2e", "#0a1628", "#111f35", "#0f1c30", "#0f2a4a", "#1e3a5f")


def test_tokens_file_has_exact_brand_values(client):
    root = _rules(_read(TOKENS))[":root"]
    for name, value in BRAND_TOKENS.items():
        assert root.get(name, "").upper() == value, name
    for st, (bg, fg) in STATUS_TOKENS.items():
        assert root[f"--st-{st}-bg"].upper() == bg and root[f"--st-{st}-fg"].upper() == fg, st
    r = client.get("/static/css/tokens.css")
    assert r.status_code == 200 and r.mimetype == "text/css"


def test_tokens_is_the_only_place_defining_colors():
    """الصفحات تحمّل tokens.css قبل app.css، وما تعاودش تعرّف :root تاعها."""
    assert ":root" not in _read(APP_CSS)
    for name in STATIC_PAGES:
        html = _page(name)
        assert TOKENS_LINK in html, name
        if "/static/css/app.css" in html:
            assert html.index(TOKENS_LINK) < html.index("/static/css/app.css"), name
        assert ":root" not in html, name


def test_legacy_variable_names_stay_defined_and_light():
    """index.html و JS يستعملو var(--card) و var(--accent)…؛ يبقاو معرّفين بألوان فاتحة."""
    root = _rules(_read(TOKENS))[":root"]
    used = set()
    for path in list(STATIC.rglob("*.html")) + list(STATIC.rglob("*.js")) + list(STATIC.rglob("*.css")):
        used |= set(re.findall(r"var\((--[\w-]+)\)", _read(path)))
    for name in TEMPLATES:
        used |= set(re.findall(r"var\((--[\w-]+)\)", _template(name)))
    assert sorted(used - set(root)) == []
    for name in ("--card", "--card2", "--sidebar", "--bg"):
        assert root[name].lower() not in DARK, name


# ── 2. الخط ──
FONT_LINK = ('<link href="https://fonts.googleapis.com/css2?family=Readex+Pro:wght@300;400;500;600;700'
             '&display=swap" rel="stylesheet"/>')


def test_pages_load_readex_pro():
    assert _rules(_read(TOKENS))[":root"]["--font"].startswith("'Readex Pro'")
    for name in STATIC_PAGES:
        html = _page(name)
        assert FONT_LINK in html, name
        assert '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>' in html, name
    for name in FEATURE_PAGES:
        body = _rules(_page(name))["body"]
        assert body["font-family"] == "var(--font)", name


def test_body_text_is_at_least_16px():
    body = _rules(_read(APP_CSS))["body"]
    assert body["font-family"] == "var(--font)"
    assert _px(body["font-size"]) >= 16
