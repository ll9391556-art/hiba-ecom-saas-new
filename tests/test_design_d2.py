# -*- coding: utf-8 -*-
"""Design D2 — لوحة التحكم كما في design/Dashboard.dc.html، بالبيانات الحقيقية.
المرجع: design/PLAN.md (D2) و design/reports/D2-plan.md. التصميم فقط: بلا تغيير فالـ API ولا الـ routes."""
import re

from tests.frontend import STATIC, page_source

CORE = (STATIC / "js" / "core.js").read_text(encoding="utf-8")


def _read(path):
    return path.read_text(encoding="utf-8")


def _index():
    return _read(STATIC / "index.html")


def _dashboard_js():
    return _read(STATIC / "js" / "dashboard.js")


# ── 1. العربية افتراضيًا ──
def test_arabic_is_the_default_language():
    """اللي ما عندوش of_lang ياخذ العربية؛ اللي اختار FR أو EN يبقالو اختيارو."""
    assert re.search(r'^var currentLang\s*=\s*localStorage\.getItem\("of_lang"\) \|\| "AR";', CORE, re.M)
    assert 'localStorage.setItem("of_lang", lang);' in CORE
    for page in ("index.html", "shop.html"):  # الصفحة تبدا RTL قبل ما يخدم JS (بلا وميض LTR)
        assert '<html lang="ar" dir="rtl">' in _read(STATIC / page), page
