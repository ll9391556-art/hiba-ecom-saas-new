# -*- coding: utf-8 -*-
"""
إعداد الاختبارات: متغيرات بيئة وهمية + fakes لـ Firebase/Gemini + منع أي اتصال شبكة.
كل هذا يحدث قبل import app لأن app.py يقرأ البيئة ويشغّل threads عند الاستيراد.
"""
import os
import socket

import pytest

# ── 1) متغيرات بيئة وهمية (تُفرض بالقوة حتى لا تتسرب قيم حقيقية من بيئة المطوّر) ──
_DUMMY_ENV = {
    "JWT_SECRET": "dummy-jwt-secret-for-tests-only-0000000000",
    # مفتاح Fernet صالح شكلياً (base64 لـ 32 بايت صفر) — وهمي
    "ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "FB_APP_SECRET": "dummy-secret",
    "META_APP_SECRET": "dummy-secret",
    "VERIFY_TOKEN": "dummy-verify-token",
    "ADMIN_API_KEY": "dummy-admin-key",
    "FB_APP_ID": "000000000000000",
    "ALLOWED_ORIGINS": "https://orderconfidence.com",
    "BOT_LAUNCHED": "true",
}
for _k, _v in _DUMMY_ENV.items():
    os.environ[_k] = _v
for _k in ("FIREBASE_CREDENTIALS", "RENDER_EXTERNAL_URL", "SENDGRID_API_KEY",
           "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SUPPORT_EMAIL_TO", "RENDER", "APP_ENV"):
    os.environ.pop(_k, None)


# ── 2) منع الشبكة نهائياً (يشمل keepalive thread وأي requests غير محاكاة) ──
from tests import fakes  # noqa: E402


def _blocked(*args, **kwargs):
    raise fakes.NetworkBlocked("Network access is disabled in tests")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked


# ── 3) fakes ثم import app ──
fakes.install()

import app as app_module  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_state():
    """قاعدة بيانات نظيفة وكاشات الذاكرة فارغة قبل كل اختبار."""
    fakes.DB.reset()
    fakes.READS.clear()
    fakes.BUCKETS.clear()
    fakes.GEMINI_CALLS.clear()
    fakes.GEMINI_RESPONDER["fn"] = None
    for name in ("_store_products_cache", "_login_attempts", "last_msg_time",
                 "_settings_cache", "_recent_bot_orders", "_health_cache"):
        getattr(app_module, name).clear()
    yield


@pytest.fixture
def app():
    app_module.app.config.update(TESTING=True)
    return app_module


@pytest.fixture
def client(app):
    return app.app.test_client()


@pytest.fixture
def db():
    return fakes.DB


def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def seed_owner():
    """ينشئ صاحب حساب (owner) بقاعدة البيانات الوهمية ويرجّع بياناته + توكن جلسة."""
    def _seed(username="owner1", uid="1001", password="dummy-pass-123", plan="pro", **extra):
        record = {"Username": username, "Password": app_module._hash_password(password),
                  "User_ID": uid, "plan": plan, "source": "local", **extra}
        fakes.DB.set(f"users/{username}", record)
        fakes.DB.set(f"uid_index/{uid}", username)
        token = app_module.issue_token(uid, username, role="owner")
        return {"username": username, "uid": uid, "password": password,
                "token": token, "headers": auth(token)}
    return _seed


@pytest.fixture
def seed_member():
    """ينشئ عضو فريق تابع لـ owner ويرجّع بياناته + توكن جلسة."""
    def _seed(owner, member_username="member1", perms=None, active=True, password="dummy-pass-123"):
        perms = app_module._clean_perms(perms or {})
        fakes.DB.set(f"team_users/{member_username}", {
            "Username": member_username, "Password": app_module._hash_password(password),
            "ownerUid": owner["uid"], "ownerUsername": owner["username"],
            "name": member_username, "permissions": perms, "active": active,
        })
        fakes.DB.set(f"data/{owner['uid']}/teamMembers/{member_username}",
                     {"name": member_username, "permissions": perms, "active": active})
        token = app_module.issue_token(owner["uid"], owner["username"], role="member",
                                       perms=perms, member_username=member_username)
        return {"username": member_username, "token": token, "headers": auth(token)}
    return _seed
