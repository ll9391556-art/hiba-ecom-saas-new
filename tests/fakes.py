# -*- coding: utf-8 -*-
"""
Fakes in-memory لـ firebase_admin و google.genai — تُحقن في sys.modules قبل استيراد app
حتى لا تتصل الاختبارات بأي خدمة حقيقية.

ملاحظة دقة: قواعد المسارات هنا تحاكي firebase_admin.db (_parse_path): رفض الأحرف
'[].?#$' وحذف المقاطع الفارغة. هذا مطابق لما نعرفه عن المكتبة، لكنه لم يُقارن
بتشغيل المكتبة الحقيقية داخل هذا المستودع.
"""
import copy
import json
import pathlib
import sys
import types

_INVALID_PATH_CHARACTERS = "[].?#$"
RULES_PATH = pathlib.Path(__file__).resolve().parent.parent / "database.rules.json"

# كل قراءة عبر FakeReference/FakeQuery تتسجّل هنا (conftest يفرغها قبل كل اختبار) —
# باش الاختبارات تتأكد مثلاً أن مسار ما ما يقراش عقدة كاملة.
READS = []


class InvalidArgumentError(Exception):
    """مثل firebase_admin.exceptions.InvalidArgumentError (HTTP 400 من REST API)."""


class NetworkBlocked(RuntimeError):
    """تُرمى عند أي محاولة اتصال شبكة أثناء الاختبارات (انظر conftest)."""


def _parse_path(path):
    if not isinstance(path, str):
        raise ValueError(f'Invalid path: "{path}". Path must be a string.')
    if any(ch in path for ch in _INVALID_PATH_CHARACTERS):
        raise ValueError(f'Invalid path: "{path}". Path contains illegal characters.')
    return [seg for seg in path.split("/") if seg]


def _key_order(k):
    # ترتيب مفاتيح RTDB: المفاتيح الرقمية (32-bit) أولاً رقمياً، ثم النصية أبجدياً
    try:
        n = int(k)
        if str(n) == k and -2**31 <= n < 2**31:
            return (0, n, "")
    except (TypeError, ValueError):
        pass
    return (1, 0, str(k))


def _ordered_copy(value):
    if isinstance(value, dict):
        return {k: _ordered_copy(value[k]) for k in sorted(value, key=_key_order)}
    return copy.deepcopy(value)


def _prune(value):
    """RTDB لا يخزّن None ولا القواميس الفارغة."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            v = _prune(v)
            if v is not None:
                out[str(k)] = v
        return out or None
    return value


class FakeDatabase:
    def __init__(self):
        self.root = {}
        self._push_counter = 0

    def reset(self):
        self.root = {}
        self._push_counter = 0

    # ── وصول منخفض المستوى (للاختبارات نفسها) ──
    def get(self, path=""):
        node = self.root
        for seg in _parse_path(path):
            if not isinstance(node, dict) or seg not in node:
                return None
            node = node[seg]
        return _ordered_copy(node)

    def set(self, path, value):
        segs = _parse_path(path)
        value = _prune(copy.deepcopy(value))
        if not segs:
            self.root = value if isinstance(value, dict) else {}
            return
        node = self.root
        for seg in segs[:-1]:
            nxt = node.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                node[seg] = nxt
            node = nxt
        if value is None:
            node.pop(segs[-1], None)
        else:
            node[segs[-1]] = value
        self._cleanup()

    def _cleanup(self):
        self.root = _prune(self.root) or {}

    def next_push_key(self):
        self._push_counter += 1
        return f"-Fake{self._push_counter:012d}"


DB = FakeDatabase()


def _load_rules():
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8")).get("rules", {})
    except FileNotFoundError:
        return {}


def _is_indexed(segments, child):
    """هل database.rules.json فيه ".indexOn" لهاد الـ child فهاد المسار؟ ($wildcard يطابق أي مقطع)."""
    node = _load_rules()
    for seg in segments:
        if not isinstance(node, dict):
            return False
        if seg in node:
            node = node[seg]
            continue
        wild = next((k for k in node if k.startswith("$")), None)
        if wild is None:
            return False
        node = node[wild]
    idx = node.get(".indexOn", []) if isinstance(node, dict) else []
    return child in ([idx] if isinstance(idx, str) else idx)


def _value_order(v):
    # ترتيب RTDB لقيم orderByChild: بلا قيمة، false، true، أرقام، نصوص، كائنات
    if v is None:
        return (0, 0)
    if v is False:
        return (1, 0)
    if v is True:
        return (2, 0)
    if isinstance(v, (int, float)):
        return (3, v)
    if isinstance(v, str):
        return (4, v)
    return (5, 0)


def _child_value(node, child_path):
    for seg in child_path.split("/"):
        if not isinstance(node, dict) or seg not in node:
            return None
        node = node[seg]
    return node


class FakeQuery:
    """نفس واجهة firebase_admin.db.Query: order_by_* ثم start_at/end_at/equal_to/limit_to_*،
    ثم get() اللي يرجّع dict مرتّب. order_by_child بلا .indexOn فالقواعد يرمي خطأ كيما REST."""

    def __init__(self, ref, order_by):
        self._ref = ref
        self._order_by = order_by
        self._bounds = {}
        self._limit_first = self._limit_last = None

    def start_at(self, value):
        self._bounds["start_at"] = value
        return self

    def end_at(self, value):
        self._bounds["end_at"] = value
        return self

    def equal_to(self, value):
        self._bounds["equal_to"] = value
        return self

    def limit_to_first(self, n):
        self._limit_first = int(n)
        return self

    def limit_to_last(self, n):
        self._limit_last = int(n)
        return self

    def _order(self, key, value):
        if self._order_by == "$key":
            return _key_order(key)
        return _value_order(_child_value(value, self._order_by))

    def _bound(self, value):
        return _key_order(str(value)) if self._order_by == "$key" else _value_order(value)

    def get(self):
        READS.append(("query", self._ref.path, self._order_by,
                      dict(self._bounds, limit_first=self._limit_first, limit_last=self._limit_last)))
        if self._order_by != "$key" and not _is_indexed(self._ref._segments, self._order_by):
            raise InvalidArgumentError(
                f'Index not defined, add ".indexOn": "{self._order_by}", for path "{self._ref.path}", to the rules')
        data = DB.get(self._ref.path)
        if not isinstance(data, dict):
            return {}
        items = sorted(data.items(), key=lambda kv: (self._order(*kv), _key_order(kv[0])))
        for name, value in self._bounds.items():
            b = self._bound(value)
            if name == "start_at":
                items = [kv for kv in items if self._order(*kv) >= b]
            elif name == "end_at":
                items = [kv for kv in items if self._order(*kv) <= b]
            else:
                items = [kv for kv in items if self._order(*kv) == b]
        if self._limit_first is not None:
            items = items[:self._limit_first]
        if self._limit_last is not None:
            items = items[-self._limit_last:] if self._limit_last else []
        return dict(items)


class FakeReference:
    def __init__(self, path=""):
        self._segments = _parse_path(path)
        self.path = "/" + "/".join(self._segments)
        self.key = self._segments[-1] if self._segments else None

    def get(self, etag=False, shallow=False):
        READS.append(("get", self.path, {"shallow": True} if shallow else {}))
        value = DB.get(self.path)
        if shallow and isinstance(value, dict):
            # نفس REST ?shallow=true: المفاتيح فقط (true للكائنات، والقيمة للبدائية)
            return {k: (True if isinstance(v, dict) else v) for k, v in value.items()}
        return value

    def order_by_child(self, path):
        if not isinstance(path, str) or not path or any(ch in path for ch in "$#[]."):
            raise ValueError(f"Illegal child path: {path}")
        return FakeQuery(self, path)

    def order_by_key(self):
        return FakeQuery(self, "$key")

    def set(self, value):
        if value is None:
            raise ValueError("Value must not be None.")
        DB.set(self.path, value)

    def update(self, value):
        if not value or not isinstance(value, dict):
            raise ValueError("Value argument must be a non-empty dictionary.")
        if None in value.keys():
            raise ValueError("Dictionary must not contain None keys.")
        for k, v in value.items():
            DB.set(f"{self.path}/{k}", v)

    def delete(self):
        DB.set(self.path, None)

    def push(self, value=""):
        if value is None:
            raise ValueError("Value must not be None.")
        key = DB.next_push_key()
        child = FakeReference(f"{self.path}/{key}")
        if value != "":
            child.set(value)
        return child

    def transaction(self, transaction_update):
        # نفس firebase-admin 6.5.0: transaction → set_if_unchanged اللي يرفض None
        # (ما تقدرش تمسح عقدة برجوع None من دالة الـ transaction).
        new_val = transaction_update(DB.get(self.path))
        if new_val is None:
            raise ValueError("Value must not be none.")
        DB.set(self.path, new_val)
        return new_val


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name
        self.public_url = f"https://storage.fake/{bucket.name}/{name}"

    def upload_from_file(self, stream, content_type=None):
        self.bucket.uploads[self.name] = {"data": stream.read(), "content_type": content_type}

    def make_public(self):
        self.bucket.public.add(self.name)


class FakeBucket:
    def __init__(self, name):
        self.name = name
        self.uploads = {}
        self.public = set()

    def blob(self, name):
        return FakeBlob(self, name)


BUCKETS = {}


def _bucket(name=None):
    name = name or "fake-bucket"
    return BUCKETS.setdefault(name, FakeBucket(name))


# ── Gemini: أي استدعاء يفشل افتراضياً؛ الاختبار يقدر يضبط GEMINI_RESPONDER ──
GEMINI_CALLS = []
GEMINI_RESPONDER = {"fn": None}


class _FakeModels:
    def generate_content(self, model, contents, config):
        GEMINI_CALLS.append({"model": model, "contents": contents, "config": config})
        fn = GEMINI_RESPONDER["fn"]
        if fn is None:
            raise RuntimeError("Gemini disabled in tests")
        text = fn(model, contents, config)
        part = types.SimpleNamespace(text=text)
        cand = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]), finish_reason="STOP")
        return types.SimpleNamespace(candidates=[cand], text=text, prompt_feedback=None)


class _FakeClient:
    def __init__(self, api_key=None, http_options=None):
        self.models = _FakeModels()


class _Part(types.SimpleNamespace):
    @classmethod
    def from_text(cls, text):
        return cls(text=text)

    @classmethod
    def from_bytes(cls, data, mime_type):
        return cls(data=data, mime_type=mime_type)


class _Config(types.SimpleNamespace):
    pass


def install():
    """يحقن الـ fakes في sys.modules. يُستدعى مرة واحدة من conftest قبل import app."""
    fa = types.ModuleType("firebase_admin")
    fa._apps = {}
    fa.initialize_app = lambda cred=None, options=None, name="[DEFAULT]": fa._apps.setdefault(name, object())
    creds = types.ModuleType("firebase_admin.credentials")
    creds.Certificate = lambda info: ("fake-cert", info)
    db = types.ModuleType("firebase_admin.db")
    db.reference = lambda path="/", app=None, url=None: FakeReference(path)
    storage = types.ModuleType("firebase_admin.storage")
    storage.bucket = lambda name=None, app=None: _bucket(name)
    fa.credentials, fa.db, fa.storage = creds, db, storage

    google = types.ModuleType("google")
    google.__path__ = []
    genai = types.ModuleType("google.genai")
    genai.Client = _FakeClient
    gtypes = types.ModuleType("google.genai.types")
    gtypes.Part = _Part
    gtypes.GenerateContentConfig = _Config
    gtypes.ThinkingConfig = _Config
    genai.types = gtypes
    google.genai = genai

    sys.modules.update({
        "firebase_admin": fa,
        "firebase_admin.credentials": creds,
        "firebase_admin.db": db,
        "firebase_admin.storage": storage,
        "google": google,
        "google.genai": genai,
        "google.genai.types": gtypes,
    })
