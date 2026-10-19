# -*- coding: utf-8 -*-
"""SEC-018 — ما كاش قيم نصية مدموجة داخل onclick="f('...')": المتصفح يفك &#39; قبل ما يشغّل JS،
فالتهريب HTML وحدو ما يحميش. القيم تمشي فـ data-* وتتقرا بـ this.dataset."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = sorted((ROOT / "static").rglob("*.html"))
# on<event>="... \''+  أو  ...,\''+  — نص JS مبني بدمج قيمة بين علامتين '
CONCAT_IN_HANDLER = re.compile(r"""on\w+=\\?"[^"]*\\''\s*\+""")


def test_pages_found():
    assert any(p.name == "index.html" for p in PAGES)


def test_no_string_values_concatenated_into_inline_handlers():
    hits = [f"{p.relative_to(ROOT)}:{i}: {line.strip()[:120]}"
            for p in PAGES
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if CONCAT_IN_HANDLER.search(line)]
    assert hits == []


def test_escAttr_helper_removed():
    assert "escAttr" not in (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_handlers_read_dataset():
    src = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for call in ("updateOrderDelivery(this.dataset.id", "updateStatus(this.dataset.id",
                 "printOrderSlip(this.dataset.id",
                 "openConversation(this.dataset.sid,this.dataset.platform,this.dataset.name)"):
        assert call in src
    disc = (ROOT / "static" / "features" / "discounts.html").read_text(encoding="utf-8")
    assert "toggleCoupon(this.dataset.code" in disc and "deleteCoupon(this.dataset.code)" in disc
