# -*- coding: utf-8 -*-
"""DEP-001 — رفع الصور بلا imghdr (حُذف من Python 3.13)."""
import io

import pytest

from tests import fakes

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG_JFIF = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20
JPEG_EXIF = b"\xff\xd8\xff\xe1\x00\x10Exif\x00" + b"\x00" * 20
GIF = b"GIF89a" + b"\x00" * 26
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16


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
