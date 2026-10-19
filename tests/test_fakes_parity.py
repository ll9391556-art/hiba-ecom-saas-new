# -*- coding: utf-8 -*-
"""الـ fake لازم يرفض نفس الحاجات اللي يرفضها firebase-admin 6.5.0 — وإلا الاختبارات
تنجح والإنتاج يطيح (كيما صرى مع nonce ديال OAuth)."""
import pytest

from tests import fakes


def test_transaction_returning_none_raises_like_sdk(db):
    db.set("x/y", {"a": 1})
    with pytest.raises(ValueError, match="Value must not be none."):
        fakes.FakeReference("x/y").transaction(lambda cur: None)
    assert db.get("x/y") == {"a": 1}  # ما تكتب والو


def test_set_and_push_none_raise_like_sdk():
    with pytest.raises(ValueError, match="Value must not be None."):
        fakes.FakeReference("x/y").set(None)
    with pytest.raises(ValueError, match="Value must not be None."):
        fakes.FakeReference("x").push(None)
