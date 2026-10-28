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


# ── البند 1: صور المنتجات ─────────────────────────────────────
def _img(fmt="PNG", size=(40, 30), color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def _open(data):
    from PIL import Image
    return Image.open(io.BytesIO(data))


def _upload(client, headers, data, name, path="/api/uploadImage"):
    return client.post(path, headers=headers, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data), name)})


def _urls(n):
    return [f"https://img.example/{i}.jpg" for i in range(n)]


def test_add_product_accepts_five_images(client, seed_owner, db):
    owner = seed_owner()
    r = client.post("/api/addProduct", headers=owner["headers"],
                    json={"data": {"name": "Montre", "images": _urls(5), "image": _urls(1)[0]}})
    assert r.status_code == 200, r.get_json()
    assert db.get(f"data/{owner['uid']}/products/Montre")["images"] == _urls(5)


@pytest.mark.parametrize("images", [_urls(6), ["javascript:alert(1)"], "https://x/1.jpg", [5]])
def test_add_product_rejects_bad_images(client, seed_owner, db, images):
    owner = seed_owner()
    r = client.post("/api/addProduct", headers=owner["headers"],
                    json={"data": {"name": "Montre", "images": images}})
    assert r.status_code == 400
    assert db.get(f"data/{owner['uid']}/products/Montre") is None


def test_update_product_rejects_six_images(client, seed_owner, db):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/products/Montre", {"name": "Montre", "sell": 100, "images": _urls(2)})
    r = client.post("/api/updateProduct", headers=owner["headers"],
                    json={"data": {"name": "Montre", "images": _urls(6)}})
    assert r.status_code == 400
    assert db.get(f"data/{owner['uid']}/products/Montre")["images"] == _urls(2)


def test_add_product_keeps_old_images_when_not_sent(client, seed_owner, db):
    """منتج قديم (حتى بأكثر من 5 صور مخزّنة) يتعاود يتحفظ بلا ما يبعث images."""
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/products/Montre", {"name": "Montre", "images": _urls(7)})
    r = client.post("/api/addProduct", headers=owner["headers"], json={"data": {"name": "Montre", "sell": 50}})
    assert r.status_code == 200
    assert db.get(f"data/{owner['uid']}/products/Montre")["images"] == _urls(7)


def test_old_product_with_single_image_is_a_one_item_list(client, seed_owner, db):
    owner = seed_owner(plan="starter")
    db.set(f"data/{owner['uid']}/products/Montre", {"name": "Montre", "sell": 100, "init": 3,
                                                    "image": "https://img.example/a.jpg"})
    r = client.get(f"/api/getStoreProducts?userId={owner['uid']}")
    assert r.get_json()["data"][0]["images"] == ["https://img.example/a.jpg"]


def test_large_photo_is_resized_to_1200(client, seed_owner):
    owner = seed_owner()
    r = _upload(client, owner["headers"], _img("JPEG", (3000, 2000)), "photo.jpg")
    assert r.status_code == 200, r.get_json()
    [up] = _stored()
    img = _open(up["data"])
    assert img.format == "JPEG" and up["content_type"] == "image/jpeg"
    assert img.size == (1200, 800)


def test_small_photo_is_not_enlarged(client, seed_owner):
    owner = seed_owner()
    r = _upload(client, owner["headers"], _img("PNG", (300, 200)), "a.png")
    assert r.status_code == 200
    assert _open(_stored()[0]["data"]).size == (300, 200)


def test_upload_over_5mb_is_rejected(client, seed_owner):
    owner = seed_owner()
    r = _upload(client, owner["headers"], b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * MB), "big.png")
    assert r.status_code == 400
    assert _stored() == []


@pytest.mark.parametrize("data,name", [
    (b"\x89PNG\r\n\x1a\n" + b"garbage" * 50, "forged.png"),
    (b"\xff\xd8\xff\xe0" + b"garbage" * 50, "forged.jpg"),
    (b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"garbage" * 50, "forged.webp"),
])
def test_forged_image_is_rejected(client, seed_owner, data, name):
    owner = seed_owner()
    r = _upload(client, owner["headers"], data, name)
    assert r.status_code == 400
    assert _stored() == []


def test_gif_is_stored_unchanged(client, seed_owner):
    owner = seed_owner()
    gif = _img("GIF", (1600, 100))
    r = _upload(client, owner["headers"], gif, "a.gif")
    assert r.status_code == 200
    assert _stored()[0]["data"] == gif


def test_reencoded_image_has_no_exif(client, seed_owner):
    from PIL import Image
    owner = seed_owner()
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    buf = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buf, format="JPEG", exif=exif)
    r = _upload(client, owner["headers"], buf.getvalue(), "a.jpg")
    assert r.status_code == 200
    assert b"SecretCam" not in _stored()[0]["data"]
