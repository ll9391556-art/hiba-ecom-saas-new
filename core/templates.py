# -*- coding: utf-8 -*-
"""قوالب HTML من templates/ (Jinja، autoescape شغّال) — بيئة مستقلة على Flask باش الصفحات
تتولّد حتى برا طلب HTTP (اختبارات، services/). Phase 4 / A9.
{{ x }} يهرّب x أوتوماتيكياً (نفس markupsafe.escape = _esc)؛ HTML جاهز يتمرّر كـ Markup."""
import pathlib

from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


def render(template_name, /, **context):
    # positional-only: قالب الهبوط عندو متغير اسمو "name"
    return _env.get_template(template_name).render(**context)
