# -*- coding: utf-8 -*-
"""المسارات العامة (بلا حساب): الصفحة الرئيسية، الصحة، الخصوصية، المتجر العام، الطلب والتتبع والتقييم، وصفحات الهبوط /lp. منقول من app.py بلا تغيير (Phase 4 / A6)."""
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from urllib.parse import quote, unquote

import requests
from flask import Blueprint, abort, jsonify, make_response, request, send_from_directory
from markupsafe import escape as _esc

from core.db import (
    _fb_call,
    _fb_get,
    _fb_patch,
    _fb_push,
    _fb_query,
    _firebase_ref,
)
from core.http import (
    err_json,
    ok_json,
)
from core.security import (
    _any_shared_limited,
)
from core.util import (
    _safe_int,
)
from services.coupons import (
    _increment_coupon_usage,
    _validate_and_apply_coupon,
)
from services.landing import (
    _build_landing_html,
    _landing_uid_from_id,
)
from services.orders import (
    _STORE_CACHE_TTL,
    _add_rating_to_stats,
    _agg_key,
    _get_stats,
    _patch_order,
    _save_order,
    _ship_values,
    _sold_by_name,
    _stock_fields,
    _store_products_cache,
    _store_products_cache_lock,
)
from services.users import (
    _get_user_record,
    _increment_usage,
    _under_cap,
)

bp = Blueprint("public", __name__)




# ── Frontend ──────────────────────────────────────────────
@bp.route("/", methods=["GET"])
def serve_index():
    return send_from_directory("static", "index.html")


@bp.route("/healthz", methods=["GET"])
def healthz():
    """liveness فقط — ديما 200 بلا Firebase. هادا اللي يتحط فـ Render Health Check Path، باش
    انقطاع قصير لـ Firebase ما يخليش Render يعاود يشغّل الخدمة ولا يفشّل deploy."""
    return jsonify({"ok": True, "service": "OrderFlow"}), 200


_health_cache = {}


_HEALTH_TTL   = 30


@bp.route("/health", methods=["GET"])
def health():
    """فحص عميق: قراءة shallow صغيرة من Firebase (النتيجة محفوظة 30 ثانية). 503 إذا طاح."""
    now = time.time()
    cached = _health_cache.get("result")
    if not cached or now - cached[0] >= _HEALTH_TTL:
        try:
            _fb_call(lambda: _firebase_ref("health").get(shallow=True))
            firebase_ok = True
        except Exception as e:
            logging.warning(f"/health: Firebase check failed ({type(e).__name__})")
            firebase_ok = False
        cached = (now, firebase_ok)
        _health_cache["result"] = cached
    firebase_ok = cached[1]
    body = {"ok": firebase_ok, "firebase": firebase_ok, "service": "OrderFlow",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return jsonify(body), (200 if firebase_ok else 503)


@bp.route("/privacy", methods=["GET"])
def privacy_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>OrderFlow AI — Privacy Policy & Terms</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Arial,sans-serif;background:#0d1b2e;color:#e8edf5;line-height:1.8}
.header{background:#0a1628;border-bottom:1px solid rgba(255,255,255,.08);padding:20px 0;text-align:center}
.header h1{font-size:28px;font-weight:800;color:#2563eb}
.header p{font-size:13px;color:#8899bb;margin-top:4px}
.container{max-width:860px;margin:0 auto;padding:40px 20px}
.section{background:#111f35;border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:28px;margin-bottom:24px}
h2{font-size:18px;font-weight:700;color:#60a5fa;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.07)}
h3{font-size:14px;font-weight:700;color:#e8edf5;margin:16px 0 8px}
p,li{font-size:13px;color:#94a3b8;margin-bottom:8px}
ul{padding-left:20px}
li{margin-bottom:6px}
.badge{display:inline-block;background:#1e3a5f;color:#60a5fa;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;margin-bottom:16px}
.contact-box{background:#0f2a4a;border:1px solid #1e3a5f;border-radius:10px;padding:16px;margin-top:12px}
.contact-box a{color:#60a5fa;text-decoration:none;font-weight:700}
.contact-box a:hover{text-decoration:underline}
.highlight{color:#10b981;font-weight:700}
.footer{text-align:center;padding:30px;color:#475569;font-size:12px;border-top:1px solid rgba(255,255,255,.07);margin-top:20px}
.tag{display:inline-block;background:rgba(37,99,235,.15);color:#60a5fa;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.product-box{background:#0a1628;border-radius:10px;padding:20px;margin-top:12px}
.product-box .feature{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.product-box .feature .icon{font-size:18px;flex-shrink:0}
.product-box .feature p{margin:0;font-size:13px;color:#94a3b8}
.product-box .feature strong{color:#e8edf5}
</style>
</head>
<body>

<div class="header">
  <h1>📦 OrderFlow AI</h1>
  <p>Complete E-Commerce Automation Platform — orderconfidence.com</p>
</div>

<div class="container">

  <div class="section">
    <span class="badge">🚀 About Our Platform</span>
    <h2>What is OrderFlow AI?</h2>
    <p>OrderFlow AI is a complete SaaS (Software as a Service) platform designed specifically for e-commerce businesses in Algeria and the Arab world. We automate the entire sales management workflow, from order intake to delivery tracking.</p>
    <div class="product-box">
      <div class="feature"><div class="icon">📦</div><div><p><strong>Order Management</strong> — Track all orders with real-time status updates (Pending, Confirmed, Delivered, Refused)</p></div></div>
      <div class="feature"><div class="icon">🤖</div><div><p><strong>AI Bot (WhatsApp & Facebook)</strong> — Gemini-powered chatbot that automatically responds to customers and creates orders from conversations</p></div></div>
      <div class="feature"><div class="icon">🛒</div><div><p><strong>Online Store</strong> — Each merchant gets a public catalog page with cart functionality for customers</p></div></div>
      <div class="feature"><div class="icon">📊</div><div><p><strong>Dashboard & Analytics</strong> — Real-time profits, confirmation rates, top products, and low stock alerts</p></div></div>
      <div class="feature"><div class="icon">🏙️</div><div><p><strong>City & Shipping Management</strong> — Configure shipping costs per city with automatic profit calculation</p></div></div>
    </div>
    <p style="margin-top:16px">Our platform serves Algerian e-commerce sellers who use Facebook, Instagram, and WhatsApp to sell products. We help them organize orders, automate responses, and grow their business.</p>
    <div style="margin-top:12px">
      <span class="tag">E-Commerce</span>
      <span class="tag">Order Management</span>
      <span class="tag">AI Chatbot</span>
      <span class="tag">WhatsApp Business</span>
      <span class="tag">Facebook Messenger</span>
      <span class="tag">Instagram DM</span>
    </div>
  </div>

  <div class="section">
    <span class="badge">🛡️ Privacy Policy</span>
    <h2>Privacy Policy</h2>
    <p><strong>Effective Date:</strong> June 17, 2026 &nbsp;|&nbsp; <strong>Last Updated:</strong> June 17, 2026</p>

    <h3>1. Information We Collect</h3>
    <p>When merchants connect their Facebook or Instagram pages to OrderFlow AI, we collect:</p>
    <ul>
      <li>Facebook Page ID and access tokens (to receive and send messages)</li>
      <li>Instagram Business Account ID and access tokens</li>
      <li>Customer messages sent to connected pages (for AI bot processing only)</li>
      <li>Order information provided by customers during conversations (name, phone, city, product)</li>
    </ul>

    <h3>2. How We Use Your Data</h3>
    <ul>
      <li><span class="highlight">Order Processing:</span> Customer messages are processed by our AI to extract order details and create orders in the merchant's dashboard</li>
      <li><span class="highlight">Automated Responses:</span> Our AI bot responds to customers on behalf of merchants</li>
      <li><span class="highlight">Analytics:</span> We calculate profits, confirmation rates, and stock levels for merchants</li>
      <li><span class="highlight">We do NOT sell, share, or transfer</span> any data to third parties</li>
    </ul>

    <h3>3. Data Storage</h3>
    <ul>
      <li>All data is stored securely in <strong>Google Firebase</strong> (Europe West region)</li>
      <li>Facebook access tokens are stored encrypted and used solely to communicate with Meta APIs</li>
      <li>Chat histories are stored per-user and accessible only to the merchant</li>
      <li>Merchants can delete their data at any time by contacting us</li>
    </ul>

    <h3>4. Meta Platform Data</h3>
    <ul>
      <li>We access Facebook and Instagram APIs only with explicit merchant permission via OAuth</li>
      <li>We only request permissions necessary for order automation: <code>pages_messaging</code>, <code>instagram_manage_messages</code>, <code>pages_read_engagement</code></li>
      <li>We do not access personal profiles, friend lists, or any data beyond page messages</li>
      <li>Merchants can disconnect their Facebook/Instagram at any time from the Settings page</li>
    </ul>

    <h3>5. Data Retention</h3>
    <p>We retain merchant data for as long as the account is active. Upon account deletion request, all associated data is permanently removed within 30 days.</p>

    <h3>6. Security</h3>
    <p>We implement industry-standard security measures including HTTPS encryption, Firebase security rules, and token-based authentication to protect your data.</p>
  </div>

  <div class="section">
    <span class="badge">📋 Terms of Service</span>
    <h2>Terms of Service</h2>
    <p><strong>Effective Date:</strong> June 17, 2026</p>

    <h3>1. Acceptance</h3>
    <p>By using OrderFlow AI, you agree to these terms. If you do not agree, please discontinue use of our platform.</p>

    <h3>2. Permitted Use</h3>
    <ul>
      <li>OrderFlow AI is intended for legitimate e-commerce businesses</li>
      <li>Users must comply with Meta's Platform Policies when using the bot features</li>
      <li>Users must not use the platform to send spam, misleading messages, or violate customer privacy</li>
      <li>Each merchant is responsible for the content of automated messages sent through their account</li>
    </ul>

    <h3>3. Subscription Plans</h3>
    <ul>
      <li><strong>Free:</strong> Basic order management and dashboard — 0 DZD</li>
      <li><strong>Starter:</strong> Includes online store — one-time payment</li>
      <li><strong>Pro:</strong> Includes AI Bot (WhatsApp + Facebook) — monthly subscription</li>
      <li><strong>Full:</strong> All features, lifetime access — one-time payment</li>
    </ul>
    <p>Plan upgrades are managed by the platform administrator. Contact us to change your plan.</p>

    <h3>4. Limitation of Liability</h3>
    <p>OrderFlow AI provides tools for order management and automation. We are not responsible for business losses, customer disputes, or issues arising from how merchants use our platform.</p>

    <h3>5. Account Termination</h3>
    <p>We reserve the right to suspend or terminate accounts that violate these terms or Meta's policies.</p>

    <h3>6. Changes to Terms</h3>
    <p>We may update these terms periodically. Continued use of the platform constitutes acceptance of updated terms.</p>
  </div>

  <div class="section">
    <span class="badge">🗑️ Data Deletion</span>
    <h2>Data Deletion Request</h2>
    <p>In compliance with Meta's Platform Policy, users can request deletion of all their data from our system.</p>
    <p>To request data deletion:</p>
    <ul>
      <li>Send an email to <strong style="color:#60a5fa">orderflowai927@gmail.com</strong> with the subject "Data Deletion Request"</li>
      <li>Include your username or User ID</li>
      <li>We will confirm deletion within <strong>30 days</strong></li>
    </ul>
    <p>You can also disconnect Facebook/Instagram at any time from <strong>Settings → Facebook/Meta → Déconnecter</strong> in the app.</p>
  </div>

  <div class="section">
    <span class="badge">📞 Contact Us</span>
    <h2>Contact Information</h2>
    <p>For questions about privacy, data, or our platform:</p>
    <div class="contact-box">
      <p>📧 <strong>Email:</strong> <a href="mailto:orderflowai927@gmail.com">orderflowai927@gmail.com</a></p>
      <p>🌐 <strong>Website:</strong> <a href="https://orderconfidence.com">https://orderconfidence.com</a></p>
      <p>📦 <strong>Platform:</strong> OrderFlow AI — E-Commerce Management SaaS</p>
      <p>📍 <strong>Location:</strong> Algeria</p>
    </div>
    <p style="margin-top:16px;font-size:12px;color:#475569">
      We typically respond to all inquiries within 48 hours.
    </p>
  </div>

</div>

<div class="footer">
  © 2026 OrderFlow AI — orderconfidence.com &nbsp;|&nbsp;
  <a href="mailto:orderflowai927@gmail.com" style="color:#60a5fa">orderflowai927@gmail.com</a>
</div>

</body>
</html>""", 200


@bp.route("/terms", methods=["GET"])
def terms_redirect():
    from flask import redirect
    return redirect("/privacy")


@bp.route("/api/addOrder", methods=["POST"])
def api_add_order():
    """مسار عام (الزبون يطلب من صفحة المتجر بلا حساب) — لذلك مقيّد بـ:
    1) التحقق أن userId ينتمي فعلاً لتاجر مسجّل (يمنع تعبئة uid عشوائي غير موجود).
    2) Rate limit حسب IP+هاتف لمنع الإغراق الآلي بطلبات وهمية يستهلك سقف التاجر الشهري.
    3) whitelist صارم لحقول الزبون + فرض status="Pending" + حساب total سيرفرياً فقط."""
    body = request.get_json(silent=True) or {}
    uid  = str(body.get("userId") or "").strip()
    raw  = body.get("data") or {}
    if not uid or not raw: return err_json("Missing fields")

    if not _get_user_record(uid):
        return err_json("Invalid store", 404)

    # request.remote_addr مُصحَّح عبر ProxyFix (بروكسي موثوق واحد) بدل هيدر خام قابل للتزوير.
    # حد مشترك بين الـ workers: لكل IP فهاد المتجر + سقف للمتجر كامل. سلة بعدة منتجات
    # (طلب لكل منتج) تدوز — الحد القديم ip:phone كل 15 ثانية كان يرفض المنتج الثاني.
    client_ip = request.remote_addr or ""
    if _any_shared_limited(("order_ip_store", f"{client_ip}|{uid}"), ("order_store", uid)):
        return err_json("محاولات كثيرة جداً — انتظر قليلاً وحاول من جديد", 429)

    if not _under_cap(uid, "orderCount", "orderCap"):
        return err_json("تم الوصول للحد الشهري من الطلبات لهذه الخطة — يرجى التواصل لترقية الخطة", 429)

    # whitelist صارم — لا نقبل من الزبون غير الموثوق أي حقل غير هذه القائمة (خصوصاً
    # status/profit/id/total التي يجب أن تُحسب أو تُفرض من السيرفر فقط).
    ALLOWED_CUSTOMER_FIELDS = {"name", "phone", "city", "product", "qty", "address", "deliveryType", "source", "couponCode", "discountApplied"}
    d = {k: v for k, v in raw.items() if k in ALLOWED_CUSTOMER_FIELDS}

    order_id       = f"ORD-{int(time.time() * 1000)}"
    d["id"]        = order_id
    d["date"]      = time.strftime("%Y-%m-%d %H:%M")
    d["status"]    = "Pending"  # ثابت دائماً — غير قابل للتعديل من الزبون بتاتاً
    d["profit"]    = 0
    d["source"]    = d.get("source") or "manual"
    d["deliveryType"] = d.get("deliveryType") if d.get("deliveryType") in ("home", "desk") else "home"
    d["date_sent"] = ""
    d["date_delivered"] = ""
    try:
        d["qty"] = max(1, int(d.get("qty", 1)))
    except Exception:
        d["qty"] = 1
    p_data = _fb_get(f"data/{uid}/products/{d.get('product')}")
    c_data = _fb_get(f"data/{uid}/cities/{d.get('city')}")
    # "total" يُحسب سيرفرياً دائماً — لا يُقبل من الزبون بتاتاً.
    if p_data and c_data:
        ship_cust, _ = _ship_values(c_data, d["deliveryType"])
        d["total"] = (float(p_data.get("sell", 0)) * d["qty"]) + ship_cust
    else:
        d["total"] = 0
               # الخصم يُعاد حسابه بالكامل هنا من قاعدة الكوبونات — discountApplied القادم
    # من الزبون لا يُستعمل نهائياً، يُتجاهل تماماً حتى لو أُرسل.
    applied_coupon = None
    if d.get("couponCode"):
        discount_amount, applied_coupon = _validate_and_apply_coupon(uid, d.get("couponCode"), d["total"])
        if applied_coupon:
            d["total"] = max(0, round(d["total"] - discount_amount, 2))
            d["couponCode"] = applied_coupon
            d["discountApplied"] = discount_amount
        else:
            d.pop("couponCode", None)
            d.pop("discountApplied", None)

    _save_order(uid, order_id, d)
    _increment_usage(uid, "orderCount")
    if applied_coupon:
        _increment_coupon_usage(uid, applied_coupon)
    return ok_json({"orderId": order_id})


def _compute_store_products(uid):
    products_raw = _fb_get(f"data/{uid}/products") or {}
    stats        = _get_stats(uid)
    sales        = _sold_by_name(stats)
    ratings      = stats.get("ratings") or {}
    result = []
    for p in products_raw.values():
        if not isinstance(p, dict) or not p.get("name"): continue
        stock     = _stock_fields(p, sales.get(p["name"], 0))
        sold, available, stat = stock["sold"], stock["available"], stock["stat"]
        images = p.get("images") or ([p["image"]] if p.get("image") else [])
        r = ratings.get(_agg_key(p["name"])) if isinstance(ratings, dict) else None
        avg_rating = rating_count = 0
        if isinstance(r, dict) and _safe_int(r.get("count")):
            rating_count = _safe_int(r.get("count"))
            avg_rating   = round(_safe_int(r.get("sum")) / rating_count, 1)
        result.append({"name": p.get("name",""), "category": p.get("category",""),
                        "size": p.get("size",""), "colors": p.get("colors",""),
                        "sell": float(p.get("sell",0)), "available": available, "stat": stat, "sold": sold,
                        "description": p.get("description",""), "image": p.get("image",""), "images": images,
                        "visible": p.get("visible","yes"), "created_at": p.get("created_at", 0),
                        "avgRating": avg_rating, "ratingCount": rating_count})
    result.sort(key=lambda x: {"In Stock":0,"Low Stock":1,"Out of Stock":2}.get(x["stat"],0))
    return result


@bp.route("/api/getStoreProducts", methods=["GET"])
def api_get_store_products():
    uid = request.args.get("userId", "").strip()
    if not uid: return err_json("Missing userId")
    with _store_products_cache_lock:
        cached = _store_products_cache.get(uid)
        if cached and time.time() - cached["ts"] < _STORE_CACHE_TTL:
            return ok_json(cached["data"])
    result = _compute_store_products(uid)
    with _store_products_cache_lock:
        _store_products_cache[uid] = {"data": result, "ts": time.time()}
    return ok_json(result)


@bp.route("/api/trackOrder", methods=["GET"])
def api_track_order():
    uid   = request.args.get("userId", "").strip()
    phone = re.sub(r"\D", "", request.args.get("phone", ""))
    if not uid or not phone: return err_json("Missing userId or phone")
    client_ip = request.remote_addr or ""
    if _any_shared_limited(("track_ip", client_ip), ("track_ip_store", f"{client_ip}|{uid}")):
        return err_json("محاولات كثيرة جداً — حاول بعد قليل", 429)
    # استعلام بالفهرس phoneDigits — قبل: تنزيل كل طلبات المتجر فكل طلب عام
    found = _fb_query(f"data/{uid}/orders", "phoneDigits", equal_to=phone)
    if found is None:
        return err_json("تعذّر البحث حالياً — حاول بعد قليل", 503)
    result = []
    for o in found.values():
        if not isinstance(o, dict): continue
        if o.get("phoneDigits") == phone:
            result.append({"id": o.get("id",""), "product": o.get("product",""),
                            "qty": o.get("qty",1), "status": o.get("status",""),
                            "date": o.get("date",""), "total": o.get("total",0),
                            "city": o.get("city",""), "rated": bool(o.get("rated", False))})
    result.sort(key=lambda x: x.get("date",""), reverse=True)
    return ok_json(result)


@bp.route("/api/submitRating", methods=["POST"])
def api_submit_rating():
    body    = request.get_json(silent=True) or {}
    uid     = str(body.get("userId") or "").strip()
    order_id= str(body.get("orderId") or "").strip()
    phone   = re.sub(r"\D", "", str(body.get("phone") or ""))
    comment = str(body.get("comment") or "").strip()[:500]
    try:
        rating = int(body.get("rating"))
    except Exception:
        return err_json("Invalid rating")
    if not uid or not order_id or not phone: return err_json("Missing fields")
    if rating < 1 or rating > 5: return err_json("Rating must be between 1 and 5")
    order = _fb_get(f"data/{uid}/orders/{order_id}")
    if not order: return err_json("Order not found", 404)
    if re.sub(r"\D", "", str(order.get("phone",""))) != phone:
        return err_json("Unauthorized", 403)
    if order.get("status") != "Delivered":
        return err_json("Order not yet delivered")
    if order.get("rated"):
        return err_json("Order already rated")
    product = order.get("product", "")
    if not product: return err_json("Invalid order")
    _fb_push(f"data/{uid}/ratings/{product}", {
        "rating": rating, "comment": comment, "date": time.strftime("%Y-%m-%d %H:%M"),
        "orderId": order_id,
    })
    _patch_order(uid, order_id, {"rated": True})
    _add_rating_to_stats(uid, product, rating)
    return ok_json(True)


@bp.route("/api/getProductRatings", methods=["GET"])
def api_get_product_ratings():
    uid     = request.args.get("userId", "").strip()
    product = request.args.get("product", "").strip()
    if not uid or not product: return err_json("Missing fields")
    raw = _fb_get(f"data/{uid}/ratings/{product}") or {}
    items = []
    if isinstance(raw, dict):
        for v in raw.values():
            if isinstance(v, dict):
                items.append({"rating": v.get("rating", 0), "comment": v.get("comment", ""), "date": v.get("date", "")})
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    return ok_json(items)


@bp.route("/api/getStoreCities", methods=["GET"])
def api_get_store_cities():
    uid = request.args.get("userId", "").strip()
    if not uid: return err_json("Missing userId")
    raw    = _fb_get(f"data/{uid}/cities") or {}
    cities = []
    for k, v in raw.items():
        if isinstance(v, dict):
            cities.append({
                "name": v.get("name", k),
                "custShip": float(v.get("custShip", 0)),
                "deskCust": float(v.get("deskCust", 0)),
            })
    return ok_json(cities)


# ── Store Settings ────────────────────────────────────────
@bp.route("/api/getStoreSettings", methods=["GET"])
def api_get_store_settings():
    uid = request.args.get("userId","").strip()
    if not uid: return err_json("Missing userId")
    return ok_json(_fb_get(f"data/{uid}/storeSettings") or {})


@bp.route("/lp/<page_id>", methods=["GET"])
def landing_page_public_view(page_id):
    uid = _landing_uid_from_id(page_id)
    if not uid:
        return "رابط غير صالح", 404
    page = _fb_get(f"data/{uid}/landingPages/{page_id}")
    if not page or not isinstance(page, dict):
        return "الصفحة غير موجودة", 404
    if not page.get("published", True):
        return "هذه الصفحة غير منشورة حالياً", 404
    try:
        _fb_patch(f"data/{uid}/landingPages/{page_id}", {"views": int(page.get("views", 0)) + 1})
    except Exception:
        pass
    html = _build_landing_html(uid, page)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}
