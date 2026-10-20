# -*- coding: utf-8 -*-
"""SEC-002 — شعار/اسم/عملة المتجر وأسماء المدن ما يقدروش يحقنوا HTML فالمتجر العام ولا فصفحة الهبوط."""
import pathlib
import re

from tests.frontend import dashboard_and_shop

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = dashboard_and_shop()  # HTML + /static/js/* (Phase 4 / F1)


def _save(client, headers, **data):
    return client.post("/api/updateStoreSettings", json={"data": data}, headers=headers)


@pytest.fixture
def owner(seed_owner, db):
    o = seed_owner()
    db.set(f"data/{o['uid']}/storeSettings", {"name": "Boutique", "logo": "🛒", "currency": "DZD"})
    return o


@pytest.mark.parametrize("bad", [
    {"logoImage": "javascript:alert(1)"},
    {"logoImage": 'https://x.test/a.png" onerror="alert(1)'},
    {"logo": {"html": "<img>"}},
    {"name": "x" * 500},
    {"currency": "<img src=x onerror=alert(1)>"},
])
def test_invalid_values_rejected_and_not_stored(client, db, owner, bad):
    r = _save(client, owner["headers"], **bad)
    assert r.status_code == 400
    stored = db.get(f"data/{owner['uid']}/storeSettings")
    assert stored == {"name": "Boutique", "logo": "🛒", "currency": "DZD"}


def test_normal_text_and_emoji_accepted_unchanged(client, db, owner):
    data = {"name": "متجر أمينة ✨ Boutique d'Amina", "tagline": "أحسن الأسعار 🇩🇿",
            "logo": "👩‍👩‍👧‍👦", "logoImage": "https://firebasestorage.googleapis.com/v0/b/x/o/logo.png?alt=media",
            "currency": "EUR"}
    assert _save(client, owner["headers"], **data).status_code == 200
    stored = db.get(f"data/{owner['uid']}/storeSettings")
    assert {k: stored[k] for k in data} == data


def test_unchanged_legacy_values_still_save(client, db, owner):
    legacy = {"name": "N" * 200, "logo": "🛒", "logoImage": "data:image/png;base64,AAAA", "currency": "DZD"}
    db.set(f"data/{owner['uid']}/storeSettings", legacy)
    # الواجهة تعاود تبعث كل الحقول عند الحفظ
    r = _save(client, owner["headers"], **legacy, tagline="slogan جديد")
    assert r.status_code == 200
    assert db.get(f"data/{owner['uid']}/storeSettings")["tagline"] == "slogan جديد"


def test_long_city_name_rejected(client, owner):
    r = client.post("/api/addCity", json={"data": {"name": "c" * 300}}, headers=owner["headers"])
    assert r.status_code == 400


def test_landing_title_escapes_store_name(client, db, owner):
    uid = owner["uid"]
    db.set(f"data/{uid}/storeSettings/name", "</title><script>alert(1)</script>")
    pid = f"LP{uid}T1"
    db.set(f"data/{uid}/landingPages/{pid}", {"name": "Sac", "published": True})
    body = client.get(f"/lp/{pid}").get_data(as_text=True)
    assert "<script>alert(1)" not in body


def test_storefront_escapes_logo_city_and_currency():
    shop = INDEX[INDEX.index("async function loadShopData"):]
    shop = shop[:shop.index("sh_renderCategories();")]
    assert "esc(s.logoImage)" in shop and "esc(s.logo||" in shop
    assert not re.search(r"'\+c\.name\+'", shop)
    assert "'+s.logoImage+'" not in shop
    assert re.search(r"function curSym\(\)\{[^}]*esc\(merchantCurrency\)", INDEX)
    assert re.search(r"function sh_cur\(\)\{[^}]*esc\(SHOP_CURRENCY\)", INDEX)
    preview = INDEX[INDEX.index("function renderStoreLogoPreview"):][:400]
    assert "esc(currentStoreLogoImage)" in preview
