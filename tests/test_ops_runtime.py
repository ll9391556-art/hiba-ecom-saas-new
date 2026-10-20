# -*- coding: utf-8 -*-
"""Phase 3 / branch 8 — إعدادات التشغيل: gunicorn من البيئة، رفض الإقلاع فالإنتاج بلا أسرار،
keepalive وحيد فـ master gunicorn، و/health يفحص Firebase بينما /healthz ديما 200."""
import importlib.util
import os
import pathlib
import subprocess
import sys
import threading

import pytest

from tests import fakes

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOOD_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

_BOOT = (
    "import socket, sys\n"
    f"sys.path.insert(0, {str(ROOT)!r})\n"
    "from tests import fakes\n"
    "def _b(*a, **k): raise fakes.NetworkBlocked('blocked')\n"
    "socket.create_connection = _b; socket.socket.connect = _b; socket.getaddrinfo = _b\n"
    "fakes.install()\n"
    "import app\n"
)


def _boot(**env):
    base = {k: v for k, v in os.environ.items()
            if k not in ("JWT_SECRET", "ENCRYPTION_KEY", "RENDER", "APP_ENV", "FIREBASE_CREDENTIALS")}
    base.update({"PYTHONIOENCODING": "utf-8", "META_APP_SECRET": "dummy-secret", "VERIFY_TOKEN": "v"})
    base.update(env)
    return subprocess.run([sys.executable, "-c", _BOOT], cwd=ROOT, env=base, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


# ── رفض الإقلاع فالإنتاج ─────────────────────────────────
@pytest.mark.parametrize("prod_env", [{"RENDER": "true"}, {"APP_ENV": "production"}])
def test_production_refuses_to_boot_without_secrets(prod_env):
    proc = _boot(**prod_env)
    assert proc.returncode != 0
    assert "JWT_SECRET" in proc.stderr and "ENCRYPTION_KEY" in proc.stderr


def test_production_refuses_invalid_encryption_key():
    proc = _boot(RENDER="true", JWT_SECRET="dummy-jwt", ENCRYPTION_KEY="not-a-fernet-key")
    assert proc.returncode != 0 and "ENCRYPTION_KEY" in proc.stderr


def test_production_boots_with_valid_secrets():
    proc = _boot(RENDER="true", JWT_SECRET="dummy-jwt", ENCRYPTION_KEY=GOOD_KEY)
    assert proc.returncode == 0, proc.stderr


def test_development_still_boots_without_secrets():
    proc = _boot()
    assert proc.returncode == 0, proc.stderr
    assert "JWT_SECRET" in proc.stderr  # تحذير، ماشي خطأ


# ── keepalive: ماشي فكل worker ───────────────────────────
def test_import_does_not_start_a_keepalive_thread(app):
    assert not hasattr(app, "_keepalive_loop")
    assert not any("keepalive" in t.name.lower() for t in threading.enumerate())


def _load_conf(monkeypatch, **env):
    for k in ("PORT", "WEB_CONCURRENCY", "GUNICORN_THREADS", "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("gunicorn_conf_test", ROOT / "gunicorn.conf.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gunicorn_conf_defaults(monkeypatch):
    conf = _load_conf(monkeypatch)
    assert conf.bind == "0.0.0.0:10000"
    assert (conf.workers, conf.threads, conf.worker_class, conf.timeout) == (2, 8, "gthread", 120)
    assert not hasattr(conf, "preload_app") or conf.preload_app is False


def test_gunicorn_conf_reads_env(monkeypatch):
    conf = _load_conf(monkeypatch, PORT="7860", WEB_CONCURRENCY="3", GUNICORN_THREADS="4")
    assert (conf.bind, conf.workers, conf.threads) == ("0.0.0.0:7860", 3, 4)


def test_keepalive_starts_once_in_master_and_only_with_url(monkeypatch):
    started = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: started.append(self.name))
    conf = _load_conf(monkeypatch)
    conf.when_ready(server=None)
    assert started == []                                   # بلا RENDER_EXTERNAL_URL: ما كاين حتى ping
    conf = _load_conf(monkeypatch, RENDER_EXTERNAL_URL="https://orderconfidence.com/")
    conf.when_ready(server=None)
    assert started == ["keepalive"]
    assert conf.KEEPALIVE_URL == "https://orderconfidence.com/healthz"


def test_dockerfile_and_procfile_use_the_config_file():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    proc = (ROOT / "Procfile").read_text(encoding="utf-8")
    assert 'CMD ["gunicorn", "app:app"]' in docker and "7860" not in docker and "--workers" not in docker
    assert proc.strip() == "web: gunicorn app:app"


# ── /health و /healthz ───────────────────────────────────
def test_healthz_is_always_ok(client, monkeypatch):
    monkeypatch.setattr(fakes.FakeReference, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json()["ok"] is True


def test_health_checks_firebase(client, app, monkeypatch):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json()["firebase"] is True
    app._health_cache.clear()

    class UnavailableError(Exception):
        pass

    monkeypatch.setattr("core.db.sleep", lambda s: None)  # retry يعيش فـ core.db
    monkeypatch.setattr(fakes.FakeReference, "get", lambda *a, **k: (_ for _ in ()).throw(UnavailableError()))
    r = client.get("/health")
    assert r.status_code == 503 and r.get_json()["firebase"] is False


def test_health_result_is_cached(client, app, monkeypatch):
    app._health_cache.clear()
    client.get("/health")
    n = len(fakes.READS)
    client.get("/health")
    assert len(fakes.READS) == n
