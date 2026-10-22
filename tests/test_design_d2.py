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


# ── 8. آخر الطلبيات ──
def test_recent_orders_table():
    sec = _dash_section()
    card = sec[sec.index('id="recentOrdersCard"'):]
    card = card[:card.index("</section>")]
    heads = re.findall(r'<th data-i18n="(\w+)"', card)
    assert heads == ["order_col", "client", "product", "city", "total", "status"]  # 6 أعمدة كيما التصميم
    assert 'id="recentOrdersTbl"' in card and """data-on-click="showSection('orders')\"""" in card
    js = _dashboard_js()
    fn = js[js.index("async function loadRecentOrders("):]
    fn = fn[:fn.index("\n}\n")]
    assert 'apiGet("/getOrders", {limit:5})' in fn
    for f in ("o.id", "o.name", "o.product", "o.city"):
        assert f"esc({f}" in fn, f
    assert "esc(stLabel(o.status))" in fn and 'Confirmed:"bc"' in fn
    assert not re.search(r"\+o\.\w+\+", fn)  # حتى قيمة بلا esc
    assert "loadRecentOrders();" in js


# ── 9. بطاقة البوت: القنوات وعدّاد الردود ──
def test_bot_card_markup():
    sec = _dash_section()
    card = sec[sec.index('id="botCard"'):]
    card = card[:card.index("</section>")]
    assert 'data-i18n="bot_card_title"' in card and 'id="channelList"' in card
    for i in ("botUsage", "botUsageText", "botUsageFill"):
        assert f'id="{i}"' in card, i
    row = sec[sec.index('id="recentOrdersCard"'):]
    assert row.index('class="dash-col"') < row.index('id="botCard"')  # جنب آخر الطلبيات


def test_bot_card_logic():
    js = _dashboard_js()
    fn = js[js.index("async function loadBotCard("):]
    fn = fn[:fn.index("\n}\n")]
    assert 'planHas("bot")' in fn and "BOT_LAUNCHED" in fn and 'apiGet("/getBotSettings", {})' in fn
    for field in ("page_id_FB", "fb_access_token", "Page_ID_instgram", "instgram_access_token",
                  "phone_number_id", "whtsapp_token"):
        assert f"s.{field}" in fn, field
    assert 't("bot_usage_x_of_y")' in fn and "PLAN_USAGE" in fn and 't("bot_not_in_plan")' in fn
    assert "esc(t(" in fn
    plan = js[js.index("async function loadUserPlan("):js.index("function planHas(")]
    assert "loadBotCard();" in plan  # PLAN_FEATURES يوصل من بعد اللوحة
    r = _css_rules()
    assert r[".usage-track"]["height"] == "8px" and r[".usage-fill"]["background"] == "var(--brand)"
    assert r[".usage-fill.warn"]["background"] == "var(--yellow)" and r[".usage-fill.full"]["background"] == "var(--flash)"


# ── 10. الأكثر مبيعًا: قائمة بأشرطة، والاسم الطويل يتقطّع بـ "…" ──
def test_top_sellers_list_replaces_chart_and_table():
    sec = _dash_section()
    assert 'id="chartProducts"' not in sec and "renderProductsChart" not in _dashboard_js()
    col = sec[sec.index('class="dash-col"'):]
    assert col.index('id="botCard"') < col.index('<ul class="top-list" id="topProductsTbl">')
    js = _dashboard_js()
    fn = js[js.index('getElementById("topProductsTbl")'):]
    fn = fn[:fn.index('.join("")')]
    assert '<span class="top-name" title="\'+esc(p.name)+\'">\'+esc(p.name)+\'</span>' in fn  # الاسم كامل فـ title
    assert "esc(p.qty)" in fn
    assert "maxQty" in fn and 'class="usage-fill"' in fn
    r = _css_rules()
    name = r[".top-name"]
    assert name["text-overflow"] == "ellipsis" and name["white-space"] == "nowrap" and name["overflow"] == "hidden"
    assert name["min-width"] == "0"


# ── 11. مخزون منخفض ──
def test_low_stock_card():
    sec = _dash_section()
    assert not re.search(r'class="(row|col-[\w-]+|table-wrap|chart-card)[ "]', sec)  # كل اللوحة بالبطاقات الجديدة
    card = sec[sec.index('id="lowStockCard"'):]
    card = card[:card.index("</section>")]
    assert re.findall(r'<th data-i18n="(\w+)"', card) == ["product", "remaining", "stock_status"]
    assert '<table class="dash-table dash-table-sm">' in card and 'id="lowStockTbl"' in card
    js = _dashboard_js()
    assert "esc(t(\"stock_ok\"))" in js
    assert _css_rules()[".dash-table-sm"]["min-width"] == "0"


# ── 12. أيقونات Lucide بدل الإيموجي فالعناوين ──
LUCIDE = ('<script src="https://cdn.jsdelivr.net/npm/lucide@0.468.0/dist/umd/lucide.min.js" '
          'integrity="sha384-uTYyvsSSUZeaPhb5RbKlQa0zY/WpX/QHfvg2mczXyBQOpkWPEDy9lczyp+w7SKXu" '
          'crossorigin="anonymous"></script>')
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u23F3]")


def test_lucide_is_pinned_with_sri_and_drawn():
    html = _index()
    assert LUCIDE in html and html.index(LUCIDE) < html.index('<script src="/static/js/core.js">')
    assert "function drawIcons()" in CORE and "lucide.createIcons({icons: lucide.icons" in CORE
    main = _read(STATIC / "js" / "main.js")
    assert main.index("applyLang(currentLang);") < main.index("drawIcons();")


def test_headings_have_icons_not_emoji():
    html = _index()
    for level, text in re.findall(r"<h([1-6])[^>]*>([\s\S]*?)</h\1>", html):
        assert not EMOJI.search(text), text
    heading_keys = set()
    for _, text in re.findall(r"<h([1-6])[^>]*>([\s\S]*?)</h\1>", html):
        heading_keys |= set(re.findall(r'data-i18n="(\w+)"', text))
    heading_keys |= set(re.findall(r'<h[1-6][^>]*data-i18n="(\w+)"', html))
    for lang in ("FR", "AR", "EN"):
        block = re.search(r"\n  %s:\{(.*?)\n  \}" % lang, CORE, re.S).group(1)
        for key in heading_keys:
            m = re.search(r'[,{\s]%s:"([^"]*)"' % key, block)
            assert m and not EMOJI.search(m.group(1)), f"{lang}.{key}"
    sec = _dash_section()
    for icon in ("chart-line", "chart-pie", "clipboard-list", "bot", "trophy", "triangle-alert"):
        assert f'<i data-lucide="{icon}"></i>' in sec, icon


def test_sidebar_uses_lucide():
    html = _index()
    side = html[html.index('<div id="sidebar">'):html.index('<div id="main">')]
    assert 'class="bi ' not in side
    assert len(re.findall(r'<i data-lucide="[a-z-]+"></i>', side)) >= 19
    r = _css_rules()
    assert r[".nav-item svg"]["width"] == "20px" and r[".nav-item svg"]["flex-shrink"] == "0"


# ── لقطات 360/1280: الجداول تبقى داخل بطاقاتها ──
def test_dashboard_tables_fit_their_cards():
    """لقطة 1280: شارة الحالة تتقصّ فآخر الطلبيات. لقطة 360: أعمدة المخزون تختفي (اسم طويل nowrap)."""
    r = _css_rules()
    assert r[".dash-table"]["min-width"] == "520px"
    assert r[".dash-ellipsis"]["max-width"] == "140px" and r[".dash-ellipsis"]["white-space"] == "nowrap"
    assert r[".dash-table td"]["white-space"] == "nowrap"
    assert r[".dash-table-sm td:first-child"]["white-space"] == "normal"
    assert r[".dash-table-wrap"]["margin"] == "0"


# ── تصليحات بعد المراجعة ──
def _trend_chart_js():
    js = _dashboard_js()
    return js[js.index("async function loadTrendChart("):]


def test_profit_curve_never_dips_below_zero():
    """tension .35 كان يرسم المنحنى تحت 0 (-2000) بين نقطتين."""
    fn = _trend_chart_js()
    assert 'cubicInterpolationMode: "monotone"' in fn and "tension:" not in fn
    assert "y: { beginAtZero: true, min: 0," in fn


def test_dashboard_numbers_have_no_thousands_separator():
    """"35200 دج" ماشي "35 200 دج"، نفس شكل ردود البوت: KPI، الجداول، المخطط (المحور والـ tooltip)."""
    js = _dashboard_js()
    fn = js[js.index("function fmtNum("):]
    fn = fn[:fn.index("\n}\n")]
    assert "return String(Math.round(Number(v)||0));" in fn
    assert re.findall(r"\.toLocaleString\(", js) == []  # toLocaleDateString للتواريخ مسموحة
    trend = _trend_chart_js()
    assert "ticks:{ color: chartTextColor(), callback: function(v){ return fmtNum(v); } }" in trend
    assert "fmtNum(ctx.parsed.y)" in trend and "fmtNum(total7)" in trend
