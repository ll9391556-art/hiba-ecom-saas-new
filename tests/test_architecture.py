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


def _imports(path):
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module.split(".")[0])
    return out


def test_lower_layers_never_import_app_or_features():
    """core/ (ثم services/) ما يستوردوش app ولا features — هادا اللي يمنع الاستيراد الدائري."""
    for layer in ("core", "services"):
        for path in sorted((ROOT / layer).glob("*.py")) if (ROOT / layer).exists() else []:
            bad = {"app", "features"} & set(_imports(path))
            assert not bad, f"{path.name} imports {bad}"


def test_app_has_no_function_level_feature_imports():
    import ast
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    nested = [n for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
              for n in ast.walk(f) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("features")]
    assert nested == []


def test_shipping_routes_served_by_shipping_blueprint(app):
    adapter = app.app.url_map.bind("localhost")
    for path, method in (("/api/shipping/status", "GET"), ("/api/shipping/connect", "POST"),
                         ("/api/shipping/disconnect", "POST"), ("/api/shipping/createShipment", "POST")):
        assert adapter.match(path, method=method)[0].startswith("shipping.")
