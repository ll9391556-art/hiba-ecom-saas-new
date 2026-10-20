# -*- coding: utf-8 -*-
"""BUG-001 — pixel-loader.js لازم يتحمّل، و trackShopEvent ما تطيحش الصفحة لو ما تحمّلش."""
import pathlib

from tests.frontend import dashboard_and_shop

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = dashboard_and_shop()  # HTML + /static/js/* (Phase 4 / F1)


def test_pixel_loader_is_served(client):
    r = client.get("/static/pixel-loader.js")
    assert r.status_code == 200
    assert b"trackShopEvent" in r.data


def test_index_references_pixel_loader():
    assert '<script defer src="/static/pixel-loader.js"></script>' in INDEX


def test_track_shop_event_fallback_defined_before_first_call():
    fallback = INDEX.find("window.trackShopEvent = window.trackShopEvent || function(){}")
    first_call = INDEX.find("trackShopEvent(")
    assert fallback != -1, "fallback for trackShopEvent is missing"
    assert first_call != -1
    assert fallback < first_call


def test_static_file_names_are_ascii():
    bad = [str(p.relative_to(ROOT)) for p in (ROOT / "static").rglob("*") if not p.name.isascii()]
    assert bad == []
