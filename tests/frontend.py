# -*- coding: utf-8 -*-
"""مصدر صفحة الواجهة كما يشوفها المتصفح: الـ HTML مع محتوى كل <script src="/static/js/...">
فبلاصتو (بنفس الترتيب). الاختبارات الثابتة كتقلّب فهاد المصدر، باش يبقاو صحاح كيفما
تقسّم الكود على ملفات (Phase 4 / F1-F5)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
_LOCAL_SCRIPT = re.compile(r'<script\b[^>]*\bsrc="/static/((?:js|css)/[^"?]+)[^"]*"[^>]*>\s*</script>')


def page_source(*pages):
    """pages: مسارات نسبية لـ static/ (مثلاً "index.html"). كيرجّع المصادر مجموعين بالترتيب."""
    out = []
    for page in pages:
        path = STATIC / page
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        out.append(_LOCAL_SCRIPT.sub(
            lambda m: m.group(0) + "\n" + (STATIC / m.group(1)).read_text(encoding="utf-8"), html))
    return "\n".join(out)


def dashboard_and_shop():
    """لوحة التحكم والمتجر العام (index.html، و shop.html من بعد F3)."""
    return page_source("index.html", "shop.html")
