# -*- coding: utf-8 -*-
"""Phase 4 / F1-F5 — بنية الواجهة بلا build: CSS وJS فملفات ثابتة، تتحمّل بنفس الترتيب."""
from tests.frontend import STATIC


def test_index_loads_css_and_js_files(client):
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/static/css/app.css"/>' in html
    assert "<style>" not in html
    for path, mime in (("/static/css/app.css", "text/css"), ("/static/js/app.js", "text/javascript")):
        r = client.get(path)
        assert r.status_code == 200 and r.mimetype == mime
