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
