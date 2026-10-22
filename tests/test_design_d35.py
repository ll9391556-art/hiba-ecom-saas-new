# -*- coding: utf-8 -*-
"""Design D3.5 — الطلبيات والمنتجات على الهاتف كبطاقات (تحت 640px). نفس الـ <tr> يتحوّل لبطاقة
بالـ CSS (بلا رسم ثاني ولا handlers جداد)، والجدول فوق 640px ما يتبدّلش.
المرجع: design/PLAN.md (D3.5) و design/reports/D35-plan.md."""
import re

from tests.frontend import STATIC

ORDERS_HEAD = ["#", "date", "client", "phone", "product", "qty", "city", "delivery_col", "total", "profit",
               "source", "sent", "delivered_date", "status", ""]
PRODUCTS_HEAD = ["product", "category", "size", "colors", "cost", "price", "stock_init", "sold", "available",
                 "stock_status", ""]


def _read(path):
    return path.read_text(encoding="utf-8")


def _css():
    return _read(STATIC / "css" / "app.css")


def _mobile_block():
    css = _css()
    start = css.index("@media (max-width:640px){/* D3.5")
    depth, i = 0, css.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        if depth == 0:
            return css[start:i + 1]
        i += 1


def _head_keys(tbody):
    html = _read(STATIC / "index.html")
    table = html[:html.index(f'id="{tbody}"')]
    thead = table[table.rindex("<thead>"):]
    out = []
    for th in re.findall(r"<th([^>]*)>(.*?)</th>", thead, re.S):
        m = re.search(r'data-i18n="(\w+)"', th[0] + th[1])
        out.append(m.group(1) if m else re.sub(r"<[^>]+>|\s", "", th[1]))
    return out


def _row_template(js, fn_name):
    fn = js[js.index(fn_name):]
    fn = fn[:fn.index("\n}\n")]
    row = fn[fn.index("return '<tr"):]
    return row[:row.index("'</tr>';") + 8]


# ── 1. بطاقة الطلبية ──
ORDER_CELLS = ["oc-num", "oc-date", "oc-name", "oc-phone", "oc-product", "oc-qty", "oc-city", "oc-delivery",
               "oc-total", "oc-profit", "oc-source", "oc-sent", "oc-delivered", "oc-status", "oc-actions"]


def test_orders_table_head_is_unchanged():
    """فوق 640px الجدول كيما راهو: نفس الـ 15 عمود بنفس الترتيب (index.html ما يتبدّلش)."""
    assert _head_keys("ordersTbl") == ORDERS_HEAD


def test_order_row_cells_have_classes_and_labels():
    js = _read(STATIC / "js" / "orders.js")
    row = _row_template(js, "function renderOrders(")
    cells = re.findall(r"""<td class="(oc-[a-z]+)"('\+dataLabel\("(\w+)"\)\+')?""", row)
    assert [c[0] for c in cells] == ORDER_CELLS  # نفس العدد ونفس الترتيب
    labels = {c[0]: c[2] for c in cells}
    for cls, key in (("oc-name", "client"), ("oc-phone", "phone"), ("oc-product", "product"), ("oc-qty", "qty"),
                     ("oc-city", "city"), ("oc-delivery", "delivery_col"), ("oc-total", "total"),
                     ("oc-profit", "profit"), ("oc-status", "status")):
        assert labels[cls] == key, cls
    assert "<span class=\"m-only oc-id\" dir=\"ltr\">'+safeId+'</span>" in row  # رقم الطلبية فوق البطاقة
    # نفس الـ handlers ونفس الروابط
    for h in ('data-on-change="updateOrderDelivery(this.dataset.id,this.value)"',
              'data-on-change="updateStatus(this.dataset.id,this.value)"',
              'data-on-click="printOrderSlip(this.dataset.id)"', "href=\"tel:'+esc(o.phone||\"\")+'\""):
        assert row.count(h) == 1, h
    assert not re.search(r"\+o\.\w+\+", row)  # كل قيمة بـ esc


def test_order_card_layout_under_640px():
    block = _mobile_block()
    assert "#ordersTbl tr{display:grid;" in block and "grid-template-areas:" in block
    assert "#sec_orders thead{display:none}" in block or "#sec_orders thead,#sec_products thead{display:none}" in block
    assert re.search(r"#ordersTbl \.oc-num,#ordersTbl \.oc-source,#ordersTbl \.oc-sent,#ordersTbl \.oc-delivered\{display:none\}", block)
    assert "#ordersTbl td[data-label]::before{content:attr(data-label)" in block
    assert "#ordersTbl .oc-actions{position:static" in block  # بلا sticky داخل البطاقة
    assert ".m-only{display:none}" in _css()  # فوق 640px: رقم الطلبية والصورة مخفيين


def test_data_label_helper_is_shared_and_escaped():
    """دالة وحدة فـ core.js (الطلبات والمنتجات)، بلا نسخة فكل ملف."""
    core = _read(STATIC / "js" / "core.js")
    assert """function dataLabel(key){ return ' data-label="'+esc(t(key))+'"'; }""" in core
    for f in ("orders.js", "catalog.js"):
        src = _read(STATIC / "js" / f)
        assert "dataLabel(" in src and "data-label=" not in src, f


# ── 2. بطاقة المنتج ──
PRODUCT_CELLS = ["pc-name", "pc-cat", "pc-size", "pc-colors", "pc-cost", "pc-price", "pc-init", "pc-sold",
                 "pc-avail", "pc-stat", "pc-actions"]


def test_products_table_head_is_unchanged():
    assert _head_keys("productsTbl") == PRODUCTS_HEAD


def test_product_row_cells_have_classes_labels_and_thumb():
    js = _read(STATIC / "js" / "catalog.js")
    row = _row_template(js, "async function loadProducts(")
    cells = re.findall(r"""<td class="(pc-[a-z]+)"('\+dataLabel\("(\w+)"\)\+')?""", row)
    assert [c[0] for c in cells] == PRODUCT_CELLS
    labels = {c[0]: c[2] for c in cells}
    assert labels["pc-price"] == "price" and labels["pc-avail"] == "available" and labels["pc-stat"] == "stock_status"
    fn = js[js.index("async function loadProducts("):]
    fn = fn[:fn.index("\n}\n")]
    assert """'<img class="m-only pc-thumb" src="'+esc(p.image)+'" alt="" loading="lazy" width="56" height="56">'""" in fn
    assert '<span class="m-only pc-thumb pc-thumb-empty">' in fn  # بلا صورة
    assert row.count('data-on-click="deleteProduct(this.dataset.name)"') == 1
    assert not re.search(r"\+p\.\w+\+", row)


def test_product_card_layout_under_640px():
    block = _mobile_block()
    assert "#sec_orders thead,#sec_products thead{display:none}" in block
    assert "#productsTbl tr{display:grid;" in block
    assert re.search(r"#productsTbl \.pc-cat,#productsTbl \.pc-size,#productsTbl \.pc-colors,#productsTbl \.pc-cost,"
                     r"#productsTbl \.pc-init,#productsTbl \.pc-sold\{display:none\}", block)
    assert "#productsTbl .pc-actions{position:static" in block
    assert "#productsTbl .pc-thumb{display:flex;" in block
