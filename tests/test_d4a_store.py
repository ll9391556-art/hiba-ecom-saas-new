# -*- coding: utf-8 -*-
"""D4a — حد حجم الطلبات، صور المنتجات (حتى 5، تصغير 1200px)، شعار المتجر، لون المتجر."""
import io

import pytest

from tests import fakes

MB = 1024 * 1024


def _stored():
    return [u for b in fakes.BUCKETS.values() for u in b.uploads.values()]


# ── حد حجم الطلب: MAX_CONTENT_LENGTH عام (6MB) + 2MB للطلبات العادية ──
def test_max_content_length_is_set(app):
    assert app.app.config["MAX_CONTENT_LENGTH"] == 6 * MB


def test_huge_upload_is_rejected_with_json_413(client, seed_owner):
    owner = seed_owner()
    r = client.post("/api/uploadImage", headers=owner["headers"], content_type="multipart/form-data",
                    data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * (7 * MB)), "big.png")})
    assert r.status_code == 413
    assert r.get_json()["status"] == "error"
    assert _stored() == []


def test_huge_json_is_rejected_with_json_413(client):
    r = client.post("/api/addOrder", data=b"{" + b" " * (7 * MB) + b"}", content_type="application/json")
    assert r.status_code == 413
    assert r.get_json()["status"] == "error"


def test_normal_requests_keep_the_2mb_limit(client):
    r = client.post("/api/addOrder", data=b"{" + b" " * (3 * MB) + b"}", content_type="application/json")
    assert r.status_code == 413
    assert r.get_json()["status"] == "error"


def test_uploads_between_2mb_and_6mb_reach_the_route(client, seed_owner):
    """قبل: limit_size (2MB) كان يرفض أي رفع فوق 2MB قبل ما يوصل للمسار."""
    owner = seed_owner()
    r = client.post("/api/uploadImage", headers=owner["headers"], content_type="multipart/form-data",
                    data={"file": (io.BytesIO(b"<html>" + b"x" * (3 * MB)), "a.png")})
    assert r.status_code == 400  # وصل للمسار ورُفض لأنه ماشي صورة، ماشي 413
