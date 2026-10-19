# -*- coding: utf-8 -*-
"""/api/saas firebaseSet بلا قيمة: firebase-admin يرفض set(None)، فكان المسار يرجّع ok
بلا ما يكتب والو. دابا يرجّع خطأ واضح."""


def _set(client, owner, **body):
    return client.post("/api/saas", headers=owner["headers"],
                       json={"action": "firebaseSet", "path": f"data/{owner['uid']}/notes", **body})


def test_firebase_set_without_value_is_an_error(client, db, seed_owner):
    owner = seed_owner()
    db.set(f"data/{owner['uid']}/notes", "old")
    r = _set(client, owner)
    assert r.status_code == 400 and r.get_json()["status"] == "error"
    assert db.get(f"data/{owner['uid']}/notes") == "old"


def test_firebase_set_with_value_still_works(client, db, seed_owner):
    owner = seed_owner()
    r = _set(client, owner, payload={"a": 1})
    assert r.get_json() == {"status": "ok", "data": True}
    assert db.get(f"data/{owner['uid']}/notes") == {"a": 1}
