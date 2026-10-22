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


# ── 2. الترجمة الناقصة ──
DASHBOARD_JS = ["core.js", "actions.js", "auth.js", "api.js", "dashboard.js", "orders.js", "catalog.js",
                "store.js", "messaging.js", "settings.js", "ui.js", "theme.js", "main.js", "shop.js"]


def _i18n_keys(lang):
    block = re.search(r"\n  %s:\{(.*?)\n  \}" % lang, CORE, re.S).group(1)
    return set(re.findall(r'(?:^|[,{\s])(\w+):"', block))


def _used_keys():
    html = _index()
    js = "\n".join(_read(STATIC / "js" / f) for f in DASHBOARD_JS)
    keys = set(re.findall(r'data-i18n(?:-placeholder)?="(\w+)"', html))
    keys |= set(re.findall(r"""\bt\(\s*["'](\w+)["']\s*\)""", js + html))
    return keys


def test_every_used_key_is_translated_in_three_languages():
    """t("sold") ما كانش معرّف → يطلع "sold" (و"SOLD" بـ uppercase تاع th)."""
    used = _used_keys()
    for lang in ("FR", "AR", "EN"):
        assert sorted(used - _i18n_keys(lang)) == [], lang


# نصوص تبقى كما هي فكل اللغات: أسماء العلامات، الباقات، الأرقام، الرموز
_ALLOWED_TEXT = re.compile(
    r"^[^\w\s]*\s*(OrderFlow|FR|AR|EN|Free|Starter|Pro|Business|DZD|WooCommerce|Facebook / Meta|Webhook URL:|#|"
    r"https?://\S+|AIza\.\.\.|ck_\.\.\.|cs_\.\.\.|\+213\.\.\.|[\d,. ]+|[^\w]+)$")


def _visible_untranslated(html):
    from html.parser import HTMLParser

    class P(HTMLParser):
        VOID = {"input", "img", "meta", "link", "br", "hr", "source"}

        def __init__(self):
            super().__init__()
            self.stack, self.out = [], []

        def _skip(self):
            return any(t in ("script", "style") or "hidden" in a or "data-i18n" in a for t, a in self.stack)

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if "placeholder" in a and "data-i18n-placeholder" not in a and not _ALLOWED_TEXT.match(a["placeholder"]):
                self.out.append(("placeholder", a["placeholder"]))
            if tag not in self.VOID:
                self.stack.append((tag, a))

        def handle_endtag(self, tag):
            while self.stack and self.stack.pop()[0] != tag:
                pass

        def handle_data(self, data):
            d = data.strip()
            if d and not self._skip() and not _ALLOWED_TEXT.match(d):
                self.out.append((self.stack[-1][0] if self.stack else "", d))

    p = P()
    p.feed(html)
    return p.out


def test_dashboard_has_no_untranslated_text():
    """كل نص ظاهر فـ index.html يمر بـ data-i18n (Tableau de bord، Reste، Stat، Pending، Copier…)."""
    assert _visible_untranslated(_index()) == []


def test_page_title_follows_the_language():
    html = _index()
    assert re.search(r'<div class="topbar-title" id="pageTitle" data-i18n="nav_dashboard">', html)
    js = _dashboard_js()
    assert 'setAttribute("data-i18n", "nav_"+s)' in js or "setAttribute('data-i18n'" in js


def test_status_and_stock_labels_are_translated():
    js = "\n".join(_read(STATIC / "js" / f) for f in ("dashboard.js", "orders.js", "catalog.js", "shop.js"))
    assert '"Pending"]' not in js and '"Pending"];' not in js  # تسمية المخطط
    assert "Total 7 jours" not in js and "7-day total" not in js
    for fn in ("function stLabel(", "function stockLabel(", "function custLabel("):
        assert fn in CORE, fn
    orders = _read(STATIC / "js" / "orders.js")
    assert "esc(stLabel(o.status))" in orders and "'>'+stLabel(s)+'</option>'" in orders
    assert "esc(stockLabel(p.stat" in _read(STATIC / "js" / "catalog.js")
    assert "esc(custLabel(c.type" in _read(STATIC / "js" / "catalog.js")
    for st in ("Pending", "Confirmed", "Delivered", "Refused", "No Answer"):  # القيم تبقى كما هي للسيرفر
        assert f'<option value="{st}" data-i18n=' in _index(), st


_FRENCH = ("Erreur", "Remplissez", "Entrez", "ajouté", "ajoutée", "Supprimé", "Supprimer ", "Sauvegardé",
           "Statut mis", "Lien copié", "Copié", "Vérification", "Plan: ", "Connecté", "Non connecté",
           "Aucun log", "Déconnect", "Client</span>", "Identifiants")


def test_no_french_messages_left_in_dashboard_js():
    for f in DASHBOARD_JS:
        if f == "shop.js":
            continue
        src = _read(STATIC / "js" / f)
        if f == "core.js":  # القاموس الفرنسي نفسو مسموح
            src = re.sub(r"\nvar I18N = \{.*?\n\};", "", src, flags=re.S)
        strings = re.findall(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', src)
        bad = [s for s in strings if any(w in s for w in _FRENCH)]
        assert bad == [], f"{f}: {bad}"
    assert not [w for w in _FRENCH if w in _index()]


# ── 3. الشريط الجانبي ──
def _css_rules():
    from tests.test_design_d1 import _rules
    return _rules(_read(STATIC / "css" / "app.css"))


def test_sidebar_is_white_with_brand_light_active_item():
    r = _css_rules()
    assert r["#sidebar"]["width"] == "248px" and r["#sidebar"]["background"] == "var(--white)"
    css = _read(STATIC / "css" / "app.css")  # _rules ما يفرّقش @media (الهاتف: 0)
    assert "#main{margin-left:248px;" in css and "html[dir=rtl] #main{margin-left:0;margin-right:248px}" in css
    item = r[".nav-item"]
    assert item["min-height"] == "46px" and item["border-radius"] == "12px"
    assert item["font-size"] == "15px" and item["font-weight"] == "600" and item["color"] == "var(--text)"
    active = r[".nav-item.active"]
    assert active["background"] == "var(--brand-light)" and active["color"] == "var(--brand-dark)"
    assert r[".nav-badge"]["background"] == "var(--flash)"
    assert r[".side-plan"]["background"] == "var(--brand-light)" and r[".side-plan"]["border-radius"] == "16px"


def test_sidebar_markup():
    html = _index()
    side = html[html.index('<div id="sidebar">'):html.index('<div id="main">')]
    assert 'src="/static/img/logo.svg" alt="" width="40" height="40"' in side
    assert 'id="navPendingBadge" class="nav-badge" hidden' in side
    plan = side[side.index('class="side-plan"'):]
    assert 'data-i18n="your_plan"' in plan and 'id="planName"' in plan
    assert 'id="managePlanLink"' in plan and """data-on-click="showSection('plans')\"""" in plan


def test_active_nav_item_follows_the_section():
    """showSection كانت تقرا onclick (ما بقاش من F5) → الإطار ما يتحرّكش من "الرئيسية"."""
    js = _dashboard_js()
    assert 'getAttribute("onclick")' not in js
    assert """el.getAttribute("data-on-click")==="showSection('"+s+"')\"""" in js


def test_sidebar_shows_pending_count_and_plan_name():
    js = _dashboard_js()
    assert 'getElementById("navPendingBadge")' in js and "badge.hidden = !n.pending" in js
    assert 'getElementById("planName")' in js and "Plan: " not in js


# ── 4. رأس اللوحة ──
def _dash_section():
    html = _index()
    return html[html.index('<div id="sec_dashboard"'):html.index('<div id="sec_orders"')]


def test_dashboard_header_greets_and_offers_new_order():
    sec = _dash_section()
    head = sec[sec.index('class="dash-head"'):sec.index('id="dashCards"')]
    assert '<h1 class="dash-hello" id="dashHello">' in head and 'data-i18n="dash_summary"' in head
    assert """data-on-click="openModal('addOrderModal')\"""" in head and 'data-i18n="new_order"' in head
    js = _dashboard_js()
    assert 'getElementById("dashHello")' in js and 't(hour<12 ? "hello_morning" : "hello_evening")' in js
    r = _css_rules()
    assert r[".dash-hello"]["font-size"] == "30px" and r[".dash-sub"]["color"] == "var(--muted)"


# ── 5. بطاقات KPI ──
def test_kpi_cards_markup():
    sec = _dash_section()
    grid = sec[sec.index('<div class="kpi-grid" id="dashCards">'):]
    grid = grid[:grid.index("\n\n")]
    cards = re.findall(r'<div class="(kpi[^"]*)">', grid)
    assert cards == ["kpi kpi-brand", "kpi", "kpi", "kpi kpi-volt"]  # الطلبات brand، الأرباح volt
    for i in ("d_total", "d_conf", "d_ref", "d_profit"):  # نفس الـ ids
        assert f'class="kpi-num' in grid and f'id="{i}"' in grid and f'id="{i}_sub"' in grid, i
    assert '<span class="kpi-pill" id="d_total_sub"' in grid


def test_kpi_number_stays_on_one_line():
    r = _css_rules()
    num = r[".kpi-num"]
    assert num["white-space"] == "nowrap" and num["line-height"] == "1"
    assert num["font-size"].startswith("clamp(28px") and num["font-size"].endswith("44px)")
    sub = r[".kpi-sub"]
    assert sub["font-size"] == "14px" and sub["display"] == "block"
    assert r[".kpi"]["border-radius"] == "var(--r-card)" and r[".kpi"]["min-width"] == "0"
    assert r[".kpi-brand"]["background"] == "var(--brand)" and r[".kpi-volt"]["background"] == "var(--volt)"
    assert r[".kpi-pill"]["background"] == "var(--volt)"
    assert r[".kpi-grid"]["grid-template-columns"] == "repeat(auto-fit,minmax(min(100%,220px),1fr))"


def test_kpi_values_and_details():
    js = _dashboard_js()
    assert 'getElementById("d_conf").textContent  = fmtNum(n.confirmedOnly + n.delivered)' in js
    assert '" ("+d.delivered' not in js  # الرقم وحدو، والتفصيل تحتو
    for key in ("kpi_pending", "kpi_delivered_of", "kpi_refuse_rate", "kpi_week_profit"):
        assert f't("{key}")' in js, key
    assert "function fmtNum(" in js


# ── 6. ألوان Chart.js من tokens.css ──
CHART_JS = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js" '
            'integrity="sha384-NrKB+u6Ts6AtkIhwPixiKTzgSKNblyhlk0Sohlgar9UHUBzai/sgnNNWWd291xqt" '
            'crossorigin="anonymous"></script>')


def test_chart_colors_come_from_tokens():
    js = _dashboard_js()
    assert "function cssVar(name)" in js and "getComputedStyle(document.documentElement)" in js
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", js) == []      # ولا لون مكتوب فـ dashboard.js
    assert "rgba(" not in js and "DARK_MODE" not in js
    assert 'borderColor: cssVar("--brand")' in js             # المنحنى
    # ألوان الحالات (شريط HTML من البند 7) من نفس tokens: .seg-* فـ app.css
    from tests.test_design_d1 import _rules
    root = _rules(_read(STATIC / "css" / "tokens.css"))[":root"]
    assert root["--yellow"].upper() == "#FFB020" and root["--flash"].upper() == "#D9230F"


def test_chart_js_is_pinned_with_sri():
    for page in ("index.html", "shop.html"):
        assert CHART_JS in _read(STATIC / page), page


# ── 7. توزيع الحالات: شريط HTML وقائمة (بلا doughnut) ──
STATUS_SEGMENTS = {"delivered": "--volt", "confirmed": "--brand", "pending": "--yellow", "refused": "--flash"}


def test_status_bar_replaces_doughnut():
    sec = _dash_section()
    assert 'id="chartStatus"' not in sec and "doughnut" not in _dashboard_js()
    assert 'class="status-bar" id="statusBar" role="img"' in sec and 'id="statusLegend"' in sec
    row = sec[sec.index('<div class="dash-row">'):]
    assert row.index('id="chartTrend"') < row.index('id="statusBar"')  # المنحنى ثم الحالات، كيما التصميم
    r = _css_rules()
    assert r[".status-bar"]["height"] == "18px" and r[".status-bar"]["border-radius"] == "var(--r-pill)"
    for name, var in STATUS_SEGMENTS.items():
        assert r[f".seg-{name}"]["background"] == f"var({var})", name
    assert r[".dash-card"]["border-radius"] == "var(--r-card)" and r[".dash-card"]["background"] == "var(--white)"


def test_status_bar_order_and_escaping():
    js = _dashboard_js()
    fn = js[js.index("function renderStatusBar("):]
    fn = fn[:fn.index("\n}\n")]
    order = [fn.index(f'["{s}"') for s in ("delivered", "confirmed", "pending", "refused")]
    assert order == sorted(order)
    assert "esc(t(r[1]))" in fn and "fmtNum(r[2])" in fn and 'setAttribute("aria-label"' in fn
