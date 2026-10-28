# -*- coding: utf-8 -*-
"""D4a (ستاتيكي) — سلايدر صور المنتجات، شعار المتجر، لون المتجر."""
import re

from tests.frontend import STATIC, page_source

SHOP = page_source("shop.html")
DASH = page_source("index.html")
SHOP_HTML = (STATIC / "shop.html").read_text(encoding="utf-8")


def _fn(src, name):
    """جسم دالة JS (من function name( حتى أول سطر يبدا بـ })."""
    m = re.search(r"function " + re.escape(name) + r"\(.*?\n\}", src, re.S)
    assert m, name
    return m.group(0)


# ── البند 1: الصور والسلايدر ──────────────────────────────────
def test_swiper_is_pinned_with_sri():
    for f, kind in (("swiper-bundle.min.js", "script"), ("swiper-bundle.min.css", "link")):
        m = re.search(r"<" + kind + r"\b[^>]*swiper@11\.1\.14/" + re.escape(f) + r"[^>]*>", SHOP_HTML)
        assert m, f
        assert 'integrity="sha384-' in m.group(0) and 'crossorigin="anonymous"' in m.group(0)
    assert SHOP_HTML.index("swiper-bundle.min.js") < SHOP_HTML.index("/static/js/shop.js")


def test_grid_uses_slider_only_for_several_images():
    media = _fn(SHOP, "sh_mediaHtml")
    assert "imgs.length===1" in media.replace(" ", "")
    assert 'loading="lazy"' in media and 'decoding="async"' in media
    assert "swiper-pagination" in media
    assert "sh_mediaHtml(" in _fn(SHOP, "sh_renderGrid")


def test_slider_options():
    init = _fn(SHOP, "sh_makeSlider")
    assert 'effect:"fade"' in init.replace(" ", "")
    assert "3000" in init
    assert "prefers-reduced-motion" in SHOP
    assert "SH_REDUCED" in init  # بلا autoplay مع reduced-motion
    assert "IntersectionObserver" in SHOP


def test_slider_timing_differs_per_product():
    assert re.search(r"\*\s*800\)\s*%\s*3000", _fn(SHOP, "sh_initSliders"))


def test_old_sliders_are_destroyed_before_rerender():
    grid = _fn(SHOP, "sh_renderGrid")
    assert "sh_destroySliders(" in grid
    assert ".destroy(" in _fn(SHOP, "sh_destroySliders")


def test_dashboard_allows_five_product_images():
    assert re.search(r"slice\(0,\s*5\s*-\s*currentProductImages\.length\)", DASH)
    assert "الصور (حتى 5)" in DASH and "Images (jusqu'à 5)" in DASH and "Images (up to 5)" in DASH
    assert "الصور (حتى 4)" not in DASH


def test_store_page_photo_change_keeps_images_in_sync():
    fn = _fn(DASH, "uploadStoreProductImage")
    assert "images" in fn


# ── البند 2: شعار المتجر ──────────────────────────────────────
def test_shop_logo_falls_back_to_first_letter():
    logo = _fn(SHOP, "sh_renderLogo")
    assert "esc(logoImage)" in logo and "esc(sh_initial(" in logo
    assert "Array.from(" in _fn(SHOP, "sh_initial")
    assert "s.logo||" not in SHOP and "s.logo ||" not in SHOP  # الإيموجي ما يبانش فالمتجر


def test_logo_shows_in_header_and_tracking():
    assert 'id="sh-logo"' in SHOP_HTML
    panel = SHOP_HTML[SHOP_HTML.index('id="track-panel"'):]
    assert 'id="track-logo"' in panel[:600] and 'id="track-name"' in panel[:600]
    load = _fn(SHOP, "loadShopData")
    assert 'sh_renderLogo(document.getElementById("sh-logo")' in load
    assert 'sh_renderLogo(document.getElementById("track-logo")' in load


def test_store_favicon_uses_logo_or_letter():
    fav = _fn(SHOP, "sh_setFavicon")
    assert '"data:image/svg+xml,"+encodeURIComponent(' in fav.replace(" ", "")
    assert "esc(" in fav
    assert "sh_setFavicon(" in _fn(SHOP, "loadShopData")


def test_dashboard_logo_upload():
    modal = DASH[DASH.index('id="storeSettingsModal"'):][:3000]
    assert 'accept="image/png,image/jpeg,image/webp"' in modal
    assert 'id="ss_logo"' not in DASH  # خانة الإيموجي تنحّات، القيمة تبقى فالبيانات
    up = _fn(DASH, "uploadStoreLogoImage")
    assert '"/uploadStoreLogo"' in up and "1024*1024" in up.replace(" ", "")
    assert "logo:" not in _fn(DASH, "saveStoreSettings").replace("logoImage:", "")


# ── البند 3: لون المتجر ───────────────────────────────────────
APP_CSS = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
TOKENS_CSS = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")


def test_shop_color_table_matches_server():
    from core.config import STORE_COLORS
    m = re.search(r"var SHOP_COLORS\s*=\s*\{(.*?)\};", SHOP, re.S)
    assert m
    js = dict((k, (a, b)) for k, a, b in re.findall(r'(\w+):\["(#[0-9A-F]{6})","(#[0-9A-F]{6})"\]', m.group(1)))
    assert js == dict(STORE_COLORS)


def test_color_is_applied_from_the_fixed_table():
    fn = _fn(SHOP, "sh_applyColor")
    assert "hasOwnProperty" in fn and '"--store"' in fn and '"--store-light"' in fn
    assert "sh_applyColor(s.color)" in _fn(SHOP, "loadShopData")


def test_store_tokens_only_on_shop_pages():
    assert re.search(r'<body class="shop-page">', SHOP_HTML)
    root = re.search(r":root\{([^}]*)\}", TOKENS_CSS).group(1)
    assert "--store:#3B2BFF" in root and "--store-light:#E6E3FF" in root  # افتراضي (test_design_d1)
    rule = re.search(r"\.shop-page\{([^}]*)\}", TOKENS_CSS).group(1)
    for decl in ("--accent:var(--store)", "--brand:var(--store)", "--brand-light:var(--store-light)"):
        assert decl in rule, decl
    assert "--flash" not in rule and "--red" not in rule  # أحمر العروض ثابت
    # اللوحة: --brand يبقى OrderFlow (ما كانش .shop-page، وما كانش var(--store) فـ index.html)
    assert "shop-page" not in DASH and "var(--store" not in DASH


def test_dashboard_color_picker():
    modal = DASH[DASH.index('id="storeSettingsModal"'):][:5000]
    values = re.findall(r'<input type="radio" name="ss_color" value="(\w+)"', modal)
    assert values == ["violet", "blue", "emerald", "orange", "pink", "mauve"]
    assert "color:" in _fn(DASH, "saveStoreSettings")
