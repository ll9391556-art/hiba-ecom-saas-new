# -*- coding: utf-8 -*-
"""جداول اللوحة تتمرّر أفقيًا داخل بطاقتها (بعد D1/D2): جدول الطلبات أعرض من الصفحة، والأعمدة على
اليسار (التوصيل، الحالة، الأزرار) كانت تتقطّع. العملاء والمدن ما كان عندهم حتى غلاف (.table-wrap فيه
overflow:hidden)، والطلبات/المنتجات كان الـ scroll غير فآخر الجدول (بعد 200 سطر)."""
import re
from html.parser import HTMLParser

from tests.frontend import STATIC
from tests.test_design_d1 import _rules

APP_CSS = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
SCROLL_CLASSES = ("table-scroll", "dash-table-wrap")


def _tables_with_ancestors(html):
    """[(attrs تاع table، [(tag, attrs) تاع كل أب])]"""
    class P(HTMLParser):
        VOID = {"input", "img", "meta", "link", "br", "hr", "source"}

        def __init__(self):
            super().__init__()
            self.stack, self.found = [], []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "table":
                self.found.append((a, list(self.stack)))
            if tag not in self.VOID:
                self.stack.append((tag, a))

        def handle_endtag(self, tag):
            while self.stack and self.stack.pop()[0] != tag:
                pass

    p = P()
    p.feed(html)
    return p.found


def _scrolls_x(rules, attrs):
    style = attrs.get("style") or ""
    if re.search(r"overflow(-x)?\s*:\s*auto", style):
        return True
    for cls in (attrs.get("class") or "").split():
        r = rules.get("." + cls, {})
        if r.get("overflow-x") == "auto" or r.get("overflow") == "auto":
            return True
    return False


def test_every_dashboard_table_is_inside_a_horizontal_scroller():
    rules = _rules(APP_CSS)
    for cls in SCROLL_CLASSES:
        assert rules["." + cls]["overflow-x"] == "auto", cls
    tables = _tables_with_ancestors((STATIC / "index.html").read_text(encoding="utf-8"))
    assert len(tables) >= 7  # الطلبات، المنتجات، العملاء، المدن، الفريق، آخر الطلبيات، المخزون
    for attrs, parents in tables:
        assert any(_scrolls_x(rules, a) for _, a in parents), attrs


def test_scroller_is_not_clipped_by_its_card():
    """الغلاف لازم يكون أضيق من الصفحة: min-width:0 وmax-width:100% (وإلا يتمدّد مع الجدول)."""
    r = _rules(APP_CSS)[".table-scroll"]
    assert r["max-width"] == "100%" and r["min-width"] == "0"
    assert "-webkit-overflow-scrolling" in r or r.get("overscroll-behavior-x") == "contain"


def test_desktop_keeps_the_horizontal_scrollbar_in_view():
    """على الحاسوب: الجدول بارتفاع محدود، فشريط التمرير الأفقي يبان بلا ما تنزل لآخر 200 طلبية."""
    block = APP_CSS[APP_CSS.index("@media (min-width:769px){.table-scroll{"):]
    block = block[:block.index("}}") + 2]
    assert "max-height:" in block and "overflow-y:auto" in block
    head = _rules(APP_CSS)[".table-scroll thead th"]
    assert head["position"] == "sticky" and head["top"] == "0"


def test_actions_column_stays_visible():
    """عمود الأزرار مثبّت فآخر السطر: يسار فـ RTL، يمين فـ FR/EN (inset-inline-end)."""
    rules = _rules(APP_CSS)
    for sel in (".has-actions td:last-child", ".has-actions th:last-child"):
        r = rules[sel]
        assert r["position"] == "sticky" and r["inset-inline-end"] == "0", sel
    assert rules[".has-actions td:last-child"]["background"] == "var(--white)"
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for tbody in ("ordersTbl", "productsTbl", "citiesTbl", "teamTbl"):
        table = html[:html.index(f'id="{tbody}"')]
        table = table[table.rindex("<table"):]
        assert table.startswith('<table class="has-actions">'), tbody


def test_feature_page_tables_scroll_too():
    """الكوبونات والتذاكر (features/) يرسمو <table> فـ JS داخل box."""
    for page, box in (("discounts.html", "couponsBox"), ("support.html", "ticketsBox")):
        html = (STATIC / "features" / page).read_text(encoding="utf-8")
        assert re.search(r"#%s\{[^}]*overflow-x:auto" % box, html), page
