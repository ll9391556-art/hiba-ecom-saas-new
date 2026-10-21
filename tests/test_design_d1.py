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


# ── 3. الشعار و favicon ──
LOGO_ARC = '<path d="M45 24.5A15 15 0 1 0 47 32" fill="none" stroke="{c}" stroke-width="7" stroke-linecap="round"/>'
LOGO_HEAD = ('<path d="M36.5 18 L46 23.5 L43.5 33" fill="none" stroke="{c}" stroke-width="7" '
             'stroke-linecap="round" stroke-linejoin="round"/>')
FAVICON_LINKS = [
    '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml"/>',
    '<link rel="icon" href="/static/favicon-32.png" sizes="32x32" type="image/png"/>',
    '<link rel="apple-touch-icon" href="/static/apple-touch-icon.png"/>',
]


@pytest.mark.parametrize("path,square,arrow", [
    ("img/logo.svg", "#3B2BFF", "#D4FF3A"),       # بنفسجي مع سهم volt
    ("img/logo-volt.svg", "#D4FF3A", "#3B2BFF"),  # volt مع سهم بنفسجي
    ("favicon.svg", "#3B2BFF", "#D4FF3A"),
])
def test_logo_svg_matches_identity(client, path, square, arrow):
    svg = _read(STATIC / path)
    assert 'viewBox="0 0 64 64"' in svg
    assert f'<rect x="0" y="0" width="64" height="64" rx="18" fill="{square}"/>' in svg
    assert LOGO_ARC.format(c=arrow) in svg and LOGO_HEAD.format(c=arrow) in svg
    r = client.get(f"/static/{path}")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"


@pytest.mark.parametrize("path,size", [("favicon-32.png", 32), ("apple-touch-icon.png", 180)])
def test_png_favicons(client, path, size):
    data = client.get(f"/static/{path}").data
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(data[16:20], "big") == size and int.from_bytes(data[20:24], "big") == size


def test_old_logo_png_is_gone():
    assert not (STATIC / "logo.png").exists()
    for path in list(STATIC.rglob("*.html")) + list(STATIC.rglob("*.js")) + list((ROOT / "templates").glob("*.html")):
        assert "logo.png" not in _read(path), path.name
    index = _page("index.html")
    assert index.count('src="/static/img/logo.svg"') == 2


def test_static_pages_have_favicon():
    for name in STATIC_PAGES:
        html = _page(name)
        for link in FAVICON_LINKS:
            assert link in html, f"{name}: {link}"


# ── 4. الأزرار ──
BUTTONS = [".btn-primary", ".btn-volt", ".btn-outline", ".btn-danger", ".btn-success"]


def test_buttons_follow_identity():
    rules = _rules(_read(APP_CSS))
    for sel in BUTTONS + [".btn-sm", ".lang-btn"]:
        r = rules[sel]
        assert r.get("border-radius") == "var(--r-btn)", sel
    for sel in BUTTONS:
        r = rules[sel]
        assert _px(r["font-size"]) >= 16 and r["font-family"] == "inherit", sel
        # الكبار 48px؛ حذف/تأكيد داخل الجداول مضغوطين (40px)، كيما .btn-sm
        assert r["min-height"] == ("var(--h-btn-sm)" if sel in (".btn-danger", ".btn-success") else "var(--h-btn)"), sel
    assert rules[".btn-sm"]["min-height"] == "var(--h-btn-sm)" and _px(rules[".btn-sm"]["font-size"]) >= 14
    assert rules[".btn-primary"]["background"] == "var(--brand)"
    assert rules[".btn-primary:hover"]["background"] == "var(--brand-dark)"
    assert rules[".btn-volt"]["background"] == "var(--volt)" and rules[".btn-volt"]["color"] == "var(--ink)"
    assert rules[".btn-outline"]["border"] == "2px solid var(--ink)"
    assert _rules(_read(TOKENS))[":root"]["--r-btn"] == "14px"


def test_reduced_motion_is_respected():
    css = _read(APP_CSS)
    block = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    assert "transition:none" in block and "transform:none" in block


# ── 5. الحالات ──
@pytest.mark.parametrize("cls,status", [
    (".bc", "confirmed"), (".bi", "delivered"), (".bp", "pending"), (".br", "refused"),
    (".bs", "delivered"),  # "متوفر" و"منشور" و"مفعّل": أخضر فاتح، ماشي لون المؤكدة
    (".bn", "neutral"),
])
def test_status_badge_colors(cls, status):
    r = _rules(_read(APP_CSS))[cls]
    assert r["background"] == f"var(--st-{status}-bg)" and r["color"] == f"var(--st-{status}-fg)"


def test_bc_is_only_for_confirmed_orders():
    """bc = طلبية مؤكدة. المخزون والنشر والتفعيل ياخذو bs."""
    js = {p.name: _read(p) for p in (STATIC / "js").glob("*.js")}
    bc_uses = [(n, line.strip()) for n, src in js.items() for line in src.split("\n")
               if re.search(r"""["' ]bc["' ]""", line)]
    assert bc_uses and all('Confirmed:"bc"' in line for _, line in bc_uses), bc_uses
    assert '"In Stock":"bs"' in js["store.js"] and "badge bs\">'+t(\"landing_published\")" in js["store.js"]
    assert "'<span class=\"badge bs\">'+t(\"active\")" in js["settings.js"]
    assert 'InStock:"bs","In Stock":"bs"' in js["catalog.js"]
    assert 'av<=5?"bn":"bs"' in js["shop.js"]


def test_body_text_is_at_least_16px():
    body = _rules(_read(APP_CSS))["body"]
    assert body["font-family"] == "var(--font)"
    assert _px(body["font-size"]) >= 16
