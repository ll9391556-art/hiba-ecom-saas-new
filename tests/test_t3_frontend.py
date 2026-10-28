# -*- coding: utf-8 -*-
"""المهمة 3 (الواجهة): أزرار تعديل وحذف الطلبية والمنتج بأيقونات Lucide، في الجدول وفي بطاقة الهاتف
(نفس السطر، D3.5)، الحذف بتأكيد وللمالك برك، وتصليح المربع الأخضر وراء أيقونات bootstrap (.bi)."""
import re

from tests.frontend import STATIC
from tests.test_design_d3 import _i18n
from tests.test_design_d35 import _row_template


def _read(*parts):
    return STATIC.joinpath(*parts).read_text(encoding="utf-8")


def _fn(src, head):
    body = src[src.index(head):]
    return body[:body.index("\n}\n")]


def _modal(html, mid):
    start = html.index(f'<div id="{mid}"')
    return html[start:html.index('<div id="', start + 10)]


# ── الطلبيات ─────────────────────────────────────────────
def test_order_row_has_lucide_print_edit_delete():
    row = _row_template(_read("js", "orders.js"), "function renderOrders(")
    actions = row[row.index('<td class="oc-actions">'):]
    for icon in ("printer", "pencil", "trash-2"):
        assert actions.count(f'<i data-lucide="{icon}"></i>') == 1, icon
    for h in ('data-on-click="printOrderSlip(this.dataset.id)"', 'data-on-click="openOrderEdit(this.dataset.id)"',
              'data-on-click="deleteOrder(this.dataset.id)"'):
        assert actions.count(h) == 1, h
    assert "bi bi-" not in actions
    assert actions.count("data-id=\"'+safeId+'\"") == 3
    assert actions.count("aria-label=\"'+esc(t(") == 3          # أزرار بأيقونة برك: اسم مقروء
    assert not re.search(r"\+o\.\w+\+", row)


def test_delete_button_is_only_drawn_for_the_owner():
    row = _row_template(_read("js", "orders.js"), "function renderOrders(")
    assert row.count('data-on-click="deleteOrder(') == 1
    assert re.search(r'\(currentRole==="owner"\s*\?\s*\'<button[^\n]*data-on-click="deleteOrder\([^\n]*\'\s*:\s*\'\'\)', row)


def test_icons_are_drawn_after_orders_render():
    assert "drawIcons();" in _fn(_read("js", "orders.js"), "function renderOrders(")


def test_delete_order_asks_first_and_drops_the_row():
    fn = _fn(_read("js", "orders.js"), "async function deleteOrder(")
    assert fn.index('confirm(t("confirm_delete_order")') < fn.index('apiPost("/deleteOrder"')
    assert "_dropOrders([orderId])" in fn


def test_polling_drops_orders_deleted_elsewhere():
    poll = _fn(_read("js", "orders.js"), "async function pollOrders(")
    assert "r.deleted" in poll and "_dropOrders(r.deleted)" in poll


def test_edit_order_modal_and_save():
    html = _read("index.html")
    modal = _modal(html, "editOrderModal")
    for fid in ("e_name", "e_phone", "e_product", "e_qty", "e_city", "e_delivery", "e_status", "e_total"):
        assert f'id="{fid}"' in modal, fid
    assert 'data-on-click="saveOrderEdit()"' in modal and "data-on-click=\"closeModal('editOrderModal')\"" in modal
    js = _read("js", "orders.js")
    save = _fn(js, "async function saveOrderEdit(")
    assert 'apiPost("/editOrder", {orderId:EDIT_ORDER_ID, data:data})' in save
    # المجموع يتبعث غير إذا التاجر بدّلو، وإلا السيرفر يحسبو
    assert re.search(r'if\(totalEl\.value!==EDIT_ORDER_TOTAL0\)\s*data\.total', save)
    actions = _read("js", "actions.js")
    for key in ("openOrderEdit(this.dataset.id)", "deleteOrder(this.dataset.id)", "saveOrderEdit()",
                "closeModal('editOrderModal')"):
        assert f'"{key}": function(event){{ {key}; }}' in actions, key


def test_edit_selects_keep_a_missing_product_or_city():
    """طلبية قديمة بمنتج ولا ولاية ماعادوش: يبقاو في القائمة باش ما يتبدّلوش بلا ما يحس التاجر."""
    fill = _fn(_read("js", "orders.js"), "function _fillSelect(")
    assert "esc(" in fill and "current" in fill


def test_t3_order_strings_in_three_languages():
    for key in ("edit", "delete", "print_slip", "edit_order", "confirm_delete_order", "order_updated",
                "order_deleted", "total_auto_hint", "save"):
        for lang in ("AR", "FR", "EN"):
            assert _i18n(lang, key), (lang, key)
    assert "{id}" in _i18n("AR", "confirm_delete_order")


# ── المنتجات ─────────────────────────────────────────────
def test_product_row_has_lucide_edit_and_delete():
    js = _read("js", "catalog.js")
    row = _row_template(js, "async function loadProducts(")
    actions = row[row.index('<td class="pc-actions">'):]
    assert actions.count('<i data-lucide="pencil"></i>') == 1 and actions.count('<i data-lucide="trash-2"></i>') == 1
    assert actions.count('data-on-click="openProductEdit(this.dataset.name)"') == 1
    assert actions.count('data-on-click="deleteProduct(this.dataset.name)"') == 1
    assert actions.count("data-name=\"'+esc(p.name)+'\"") == 2
    assert "bi bi-" not in actions
    assert "drawIcons();" in _fn(js, "async function loadProducts(")
    assert '"openProductEdit(this.dataset.name)": function(event){ openProductEdit(this.dataset.name); }' \
        in _read("js", "actions.js")


def test_product_modal_saves_an_edit_through_update_product():
    js = _read("js", "catalog.js")
    save = _fn(js, "async function addProduct(")
    assert 'apiPost(EDIT_PRODUCT_NAME ? "/updateProduct" : "/addProduct", {data:data})' in save
    # الصور تتبعث غير إذا تبدّلو (صورة قديمة بلا http ما تطيّحش التعديل)
    assert re.search(r"if\(!EDIT_PRODUCT_NAME \|\| JSON\.stringify\(currentProductImages\)!==EDIT_PRODUCT_IMAGES0\)", save)
    edit = _fn(js, "function openProductEdit(")
    assert 'openModal("addProductModal")' in edit and "setProductEditMode(" in edit
    mode = _fn(js, "function setProductEditMode(")
    assert "p_name.readOnly" in mode and 't("edit_product")' in mode
    # فتح "إضافة منتج" يخرج من وضع التعديل
    assert "setProductEditMode(null)" in _fn(_read("js", "ui.js"), "function openModal(")


def test_product_image_thumbs_are_escaped():
    """روابط الصور جاية من السيرفر في وضع التعديل: لازم esc قبل innerHTML."""
    thumbs = _fn(_read("js", "ui.js"), "function renderProductImageThumbs(")
    assert "src=\"'+esc(url)+'\"" in thumbs


def test_t3_product_strings_in_three_languages():
    for key in ("edit_product", "product_updated"):
        for lang in ("AR", "FR", "EN"):
            assert _i18n(lang, key), (lang, key)


# ── المربع الأخضر وراء أيقونات bootstrap ─────────────────
def test_bootstrap_icons_do_not_take_the_delivered_badge_color():
    """.bi = شارة "تم التسليم" (خلفية volt)، وهي نفس class تاع bootstrap-icons (<i class="bi bi-…">).
    القاعدة i.bi ترجّع الأيقونات شفافة، وقاعدة الشارة تبقى كيما هي."""
    css = _read("css", "app.css")
    badge = css.index(".bi{background:var(--st-delivered-bg);color:var(--st-delivered-fg)}")
    fix = css.index("i.bi{background:none;color:inherit}")
    assert fix > badge  # نفس الخصوصية ماشي كافية: i.bi أقوى، ومن بعد كذلك
