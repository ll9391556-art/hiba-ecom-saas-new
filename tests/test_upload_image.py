# -*- coding: utf-8 -*-
"""DEP-001 — رفع الصور بلا imghdr (حُذف من Python 3.13)."""
import io

import pytest

from tests import fakes

from PIL import Image


# D4a: الرفع يفك الصورة فعلاً، فالـ fixtures صور حقيقية صغيرة (قبل: bytes وهمية بالـ header برك)
def _real(fmt, **kw):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(buf, format=fmt, **kw)
    return buf.getvalue()


def _exif_first_jpeg():
    """JPEG يبدا بـ APP1/Exif (كيما الكاميرات) بلا مقطع JFIF."""
    exif = Image.Exif()
    exif[0x010F] = "Cam"
    data = _real("JPEG", exif=exif)
    assert data[2:4] == b"\xff\xe0"
    app0_len = int.from_bytes(data[4:6], "big")
    return data[:2] + data[4 + app0_len:]


PNG = _real("PNG")
JPEG_JFIF = _real("JPEG")
JPEG_EXIF = _exif_first_jpeg()
GIF = _real("GIF")
WEBP = _real("WEBP")


def _upload(client, headers, data, name):
    return client.post("/api/uploadImage", headers=headers, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data), name)})


def _stored():
    return [u for b in fakes.BUCKETS.values() for u in b.uploads.values()]


def test_app_no_longer_imports_imghdr(app):
    assert not hasattr(app, "imghdr")


@pytest.mark.parametrize("data,name,mime", [
    (JPEG_JFIF, "a.jpg", "image/jpeg"),
    (JPEG_EXIF, "b.jpg", "image/jpeg"),
    (PNG, "c.png", "image/png"),
    (GIF, "d.gif", "image/gif"),
    (WEBP, "e.webp", "image/webp"),
])
def test_valid_images_are_accepted(client, seed_owner, data, name, mime):
    owner = seed_owner()
    r = _upload(client, owner["headers"], data, name)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["data"]["url"]
    assert [u["content_type"] for u in _stored()] == [mime]


@pytest.mark.parametrize("data,name", [
    (b"<!DOCTYPE html><script>alert(1)</script>", "evil.jpg"),
    (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "evil.png"),
    (b"", "empty.png"),
])
def test_non_images_are_rejected(client, seed_owner, data, name):
    owner = seed_owner()
    r = _upload(client, owner["headers"], data, name)
    assert r.status_code == 400
    assert _stored() == []
