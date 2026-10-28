# -*- coding: utf-8 -*-
"""D4a — لغة المتجر: كل نص ظاهر فـ shop.html/shop.js يمر بالترجمة (AR/FR/EN)، والعربية افتراضياً.
- shop.html: كل نص (وكل placeholder/aria-label/title) فعنصر عندو data-i18n (ولا data-i18n-placeholder…).
- shop.js: ما كانش نص طبيعي مكتوب فـ string (عربي، ولا كلمتين لاتينيتين، ولا كلمة Capitalized)؛
  النص يجي من t("sh_...").
- كل مفتاح مستعمل موجود فـ AR وFR وEN."""
import re
from html.parser import HTMLParser

import pytest

from tests.frontend import STATIC

SHOP_HTML = (STATIC / "shop.html").read_text(encoding="utf-8")
SHOP_JS = (STATIC / "js" / "shop.js").read_text(encoding="utf-8")
CORE_JS = (STATIC / "js" / "core.js").read_text(encoding="utf-8")

ARABIC = re.compile(r"[؀-ۿ]")
LETTER = re.compile(r"[A-Za-zÀ-ÿ؀-ۿ]")
# أسماء ماشي للترجمة: العلامة، وقيم البيانات (الحالات، أحداث البيكسل) اللي ما تبانش كما هي
NOT_TEXT = {"OrderFlow", "No Answer", "In Stock", "Low Stock", "Out of Stock", "Pending", "Confirmed",
            "Delivered", "Refused", "Purchase", "AddToCart", "InitiateCheckout"}


def _lang_block(lang):
    m = re.search(r"\n\s*" + lang + r"\s*:\s*\{(.*?)\n\s*\}", CORE_JS, re.S)
    assert m, lang
    return set(re.findall(r'(?:^|[,{\s])"?([A-Za-z_][\w]*)"?\s*:', m.group(1)))


KEYS = {lang: _lang_block(lang) for lang in ("AR", "FR", "EN")}


# ── shop.html ────────────────────────────────────────────────
class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.bad, self.keys = [], [], set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for attr in ("placeholder", "aria-label", "title"):
            if a.get(attr) and LETTER.search(a[attr]) and a[attr] not in NOT_TEXT:
                key = a.get(f"data-i18n-{attr}")
                if not key:
                    self.bad.append(f"<{tag} {attr}={a[attr]!r}>")
                else:
                    self.keys.add(key)
        if a.get("data-i18n"):
            self.keys.add(a["data-i18n"])
        if tag not in ("meta", "link", "input", "br", "img"):
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        text = data.strip()
        if not text or not LETTER.search(text) or text in NOT_TEXT:
            return
        if any(tag in ("script", "style", "title") for tag, _ in self.stack):
            return
        if not (self.stack and self.stack[-1][1].get("data-i18n")):
            self.bad.append(text)


def _html():
    c = _Collector()
    c.feed(SHOP_HTML)
    return c


def test_every_shop_html_text_is_translated():
    assert _html().bad == []


# ── shop.js ──────────────────────────────────────────────────
def _literals(src):
    """strings ديال JS (بلا التعليقات). shop.js ما فيهش regex literals."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
        elif src.startswith("/*", i):
            i = src.index("*/", i) + 2
        elif c in "'\"`":
            j, buf = i + 1, []
            while src[j] != c:
                if src[j] == "\\":
                    buf.append(src[j + 1])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
        else:
            i += 1
    return out


def _visible_part(lit):
    """نحيّد الـ tags كاملين، وأطراف الـ tags المقطوعة، والـ attributes."""
    s = re.sub(r"<[^<>]*>", " ", lit)
    if ">" in s and "<" not in s.split(">")[0]:
        s = s.split(">", 1)[1] if re.search(r'=|^\s*"', s.split(">")[0]) else s
    s = re.sub(r"<[^>]*$", " ", s)
    s = re.sub(r'[\w-]+="[^"]*"?', " ", s)
    return s.replace('"', " ").strip()


def _is_text(part):
    if not part or part in NOT_TEXT:
        return False
    if ARABIC.search(part):
        return True
    if re.fullmatch(r"\(?[\w-]+:\s*[\w-]+\)?", part):  # CSS: (prefers-reduced-motion: reduce)
        return False
    if re.search(r"[A-Za-zÀ-ÿ]{2,}(?:[,!?.:]*\s+|['’])[A-Za-zÀ-ÿ]{2,}", part):
        return True
    return re.fullmatch(r"[^\w]*[A-ZÀ-Ý][a-zà-ÿ]{2,}[^\w]*", part) is not None


_TEXT_ATTRS = re.compile(r'(?:placeholder|title|aria-label)="([^"]*)"')


def _untranslated(lit):
    return _is_text(_visible_part(lit)) or any(_is_text(v.strip()) for v in _TEXT_ATTRS.findall(lit))


def test_shop_js_has_no_untranslated_text():
    bad = [lit for lit in _literals(SHOP_JS) if _untranslated(lit)]
    assert bad == []


def test_detector_catches_text_in_attributes():
    assert _untranslated('<textarea class="rate-comment" placeholder="تعليق (اختياري)"></textarea>')
    assert _untranslated('<button title="Supprimer le produit">')
    assert not _untranslated('<textarea placeholder="\'+esc(t("sh_rate_comment_ph"))+\'">')


@pytest.mark.parametrize("lit", ["Panier vide", "🛒 Ajouter", "Rupture", "⚡ متبقي ", "Suivre ma commande",
                                 "<div>Aucun produit</div>", '<span class="x">Total</span>'])
def test_detector_catches_text(lit):
    assert _is_text(_visible_part(lit))


@pytest.mark.parametrize("lit", ["sh-search", "none", "/getStoreSettings", "price_asc", "sh_add_to_cart",
                                 '<img src="', '" alt="', "width:100%;height:100%;object-fit:cover",
                                 "data:image/svg+xml,", '" data-on-click="sh_addToCart(this.dataset.name)">',
                                 "No Answer", "(prefers-reduced-motion: reduce)"])
def test_detector_ignores_code(lit):
    assert not _is_text(_visible_part(lit))


# ── المفاتيح ─────────────────────────────────────────────────
def test_every_used_key_exists_in_three_languages():
    used = set(re.findall(r"""\bt\(\s*["'](\w+)["']\s*\)""", SHOP_JS)) | _html().keys
    assert used, "shop ما يستعمل حتى مفتاح"
    for lang, keys in KEYS.items():
        assert sorted(used - keys) == [], lang


# ── اللغة من إعدادات المتجر ───────────────────────────────────
def _fn(name):
    m = re.search(r"function " + name + r"\(.*?\n\}", SHOP_JS, re.S)
    assert m, name
    return m.group(0)


def test_shop_language_comes_from_store_settings_default_arabic():
    apply = _fn("sh_applyLang")
    assert "localStorage" not in apply  # ما يبدّلش لغة لوحة التاجر (نفس الـ origin)
    assert '"AR"' in apply and "data-i18n" in apply and "dir" in apply
    assert "sh_applyLang(s.lang)" in _fn("loadShopData")
    assert re.search(r'<html lang="ar" dir="rtl">', SHOP_HTML)


def test_dashboard_store_language_select():
    dash = (STATIC / "index.html").read_text(encoding="utf-8")
    modal = dash[dash.index('id="storeSettingsModal"'):][:6000]
    sel = re.search(r'<select id="ss_lang"[^>]*>(.*?)</select>', modal, re.S)
    assert sel and re.findall(r'value="(\w+)"', sel.group(1)) == ["AR", "FR", "EN"]
    store_js = (STATIC / "js" / "store.js").read_text(encoding="utf-8")
    assert 'getElementById("ss_lang").value = s.lang||"AR"' in store_js
    assert 'lang:     document.getElementById("ss_lang").value' in store_js


# ── السيرفر: lang = AR/FR/EN برك ───────────────────────────────
@pytest.mark.parametrize("lang", ["AR", "FR", "EN"])
def test_valid_store_lang_is_saved(client, seed_owner, db, lang):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/storeSettings", {"name": "A"})
    r = client.post("/api/updateStoreSettings", headers=owner["headers"], json={"data": {"lang": lang}})
    assert r.status_code == 200
    assert db.get(f"data/{owner['uid']}/storeSettings")["lang"] == lang


@pytest.mark.parametrize("bad", ["ar", "DE", "<b>", "", 3, None])
def test_invalid_store_lang_is_rejected(client, seed_owner, db, bad):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/storeSettings", {"name": "A", "lang": "FR"})
    r = client.post("/api/updateStoreSettings", headers=owner["headers"], json={"data": {"lang": bad}})
    assert r.status_code == 400
    assert db.get(f"data/{owner['uid']}/storeSettings") == {"name": "A", "lang": "FR"}


def test_legacy_store_lang_still_saves_when_unchanged(client, seed_owner, db):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/storeSettings", {"name": "A", "lang": "ar-DZ"})
    r = client.post("/api/updateStoreSettings", headers=owner["headers"],
                    json={"data": {"name": "B", "lang": "ar-DZ"}})
    assert r.status_code == 200
