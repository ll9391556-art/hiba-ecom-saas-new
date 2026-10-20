# -*- coding: utf-8 -*-
"""Phase 4 — شبكة أمان لإعادة التنظيم: نفس المسارات (URL + methods) بالضبط فكل خطوة،
وكل مسار متسجّل مرة وحدة (ما كاينش نسخ ميتة)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = json.loads((ROOT / "tests" / "route_snapshot.json").read_text(encoding="utf-8"))


def _rules(app):
    return [(r.rule, ",".join(sorted(r.methods - {"HEAD", "OPTIONS"}))) for r in app.app.url_map.iter_rules()]


def test_routes_match_snapshot(app):
    assert sorted(set(_rules(app))) == sorted((r["rule"], r["methods"]) for r in SNAPSHOT)


def test_every_route_is_registered_once(app):
    rules = _rules(app)
    dupes = sorted({r for r in rules if rules.count(r) > 1})
    assert dupes == []


def test_shipping_routes_served_by_shipping_blueprint(app):
    adapter = app.app.url_map.bind("localhost")
    for path, method in (("/api/shipping/status", "GET"), ("/api/shipping/connect", "POST"),
                         ("/api/shipping/disconnect", "POST"), ("/api/shipping/createShipment", "POST")):
        assert adapter.match(path, method=method)[0].startswith("shipping.")
