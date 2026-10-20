# -*- coding: utf-8 -*-
"""صفحات الهبوط: المعرّفات، أسئلة وتوليد النص بـ Gemini، وبناء HTML العام (/lp/<id>).
منقول من app.py بلا تغيير (Phase 4 / A6)."""
import json
import logging
import re
import time
from urllib.parse import quote

from google.genai import types
from markupsafe import escape as _esc

from core.config import _JSON_END, _JSON_START
from core.db import _fb_get
from services.bot import _gemini_generate_with_fallback

# ── Landing Pages (صفحات هبوط) ─────────────────────────────
LANDING_ID_PREFIX = "LP"


def _new_landing_id(uid):
    return f"{LANDING_ID_PREFIX}{uid}T{int(time.time()*1000)}"


def _landing_uid_from_id(page_id):
    try:
        page_id = str(page_id or "")
        if not page_id.startswith(LANDING_ID_PREFIX):
            return None
        rest = page_id[len(LANDING_ID_PREFIX):]
        uid_part, sep, _ = rest.partition("T")
        return uid_part if (uid_part and sep) else None
    except Exception:
        return None


def _sanitize_image_url(u):
    """يقبل فقط روابط https/http حقيقية — يمنع حقن HTML/سكربت عبر حقل 'صورة'
    الذي يُدرج لاحقاً داخل صفحة الهبوط العامة (/lp/<id>)."""
    u = str(u or "").strip()
    if not re.match(r'^https?://[^\s"\'<>]+$', u, re.IGNORECASE):
        return ""
    return u


DEFAULT_LANDING_QUESTIONS = [
    {"id": "audience",       "question": "شكون الزبون المستهدف بالضبط؟ (مثلاً: نساء 25-40 سنة، رياضيين، عائلات...)"},
    {"id": "painPoint",      "question": "شنو أكبر مشكل أو حاجة يحلّها المنتج للزبون؟"},
    {"id": "mainBenefit",    "question": "شنو أهم فائدة أو ميزة تحب تبرزها فالصفحة؟"},
    {"id": "differentiator", "question": "شنو يميزك عن المنتجات المشابهة الموجودة فالسوق؟"},
    {"id": "offer",          "question": "كاين عرض أو تخفيض حالياً؟ (اذكر السعر الأصلي والسعر الحالي إذا كاين)"},
    {"id": "guarantee",      "question": "شنو الضمانات اللي تقدمها؟ (دفع عند الاستلام، استرجاع، ضمان جودة...)"},
    {"id": "socialProof",    "question": "عندك عدد مبيعات أو تقييمات تحب تبرزها كثقة اجتماعية؟"},
    {"id": "urgency",        "question": "تحب تضيف إحساس بالإلحاح؟ (كمية محدودة، عرض لمدة محدودة...)"},
]


def _generate_landing_questions(bot_settings, name, description, category=""):
    api_key = str(bot_settings.get("Gemini_api_key") or "").strip()
    if not api_key:
        return DEFAULT_LANDING_QUESTIONS
    try:
        prompt = f"""أنت خبير تسويق متخصص فصفحات الهبوط (Landing Pages) عالية التحويل لمتاجر التجارة الإلكترونية بالجزائر والعالم العربي.
منتج التاجر: {name}
الوصف: {description or 'غير محدد'}
الفئة: {category or 'غير محددة'}

اطرح 6 أسئلة قصيرة ومباشرة بالدارجة الجزائرية/العربية على التاجر، الهدف منها جمع المعلومات الضرورية لبناء صفحة هبوط احترافية عالية التحويل (تشمل: الجمهور المستهدف، المشكل اللي يحله المنتج، الميزة التنافسية، العرض/السعر، الضمانات، والثقة الاجتماعية/الإلحاح).
رد فقط بمصفوفة JSON بهذا الشكل بالضبط، بلا أي نص إضافي قبلها أو بعدها:
[{{"id":"معرف_قصير_بالإنجليزية","question":"نص السؤال"}}, ...]"""
        contents = [types.Part.from_text(text=prompt)]
        cfg = types.GenerateContentConfig(temperature=0.5, max_output_tokens=500)
        text, _ = _gemini_generate_with_fallback(api_key, contents, cfg, "landing_questions")
        cleaned = text.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, list) and len(parsed) >= 3:
            out = []
            for i, q in enumerate(parsed[:8]):
                if isinstance(q, dict) and q.get("question"):
                    out.append({"id": str(q.get("id") or f"q{i+1}"), "question": str(q["question"])[:200]})
            if out:
                return out
    except Exception as e:
        logging.warning(f"landing/questions: تعذّر توليد أسئلة عبر Gemini، استُعملت الأسئلة الافتراضية: {e}")
    return DEFAULT_LANDING_QUESTIONS


def _generate_landing_copy(api_key, name, description, answers):
    answers = answers if isinstance(answers, dict) else {}
    fallback = {
        "headline": name,
        "subheadline": answers.get("mainBenefit", "") or "",
        "description": description,
        "benefits": [],
        "urgencyText": answers.get("urgency", "") or "",
        "guaranteeText": answers.get("guarantee", "") or "",
        "faq": [],
    }
    if not api_key:
        return fallback
    try:
        answers_text = "\n".join(f"- {k}: {v}" for k, v in answers.items() if str(v or "").strip())
        prompt = f"""أنت كاتب إعلانات (Copywriter) خبير فصفحات الهبوط عالية التحويل لمتاجر التجارة الإلكترونية بالجزائر
(أسلوب صفحات الهبوط الأكثر انتشاراً ونجاحاً حالياً بسوق الدروبشيبينغ: عنوان قوي يلمس المشكل مباشرة، فوائد قصيرة
بشكل نقاط مع إيموجي مناسب، ثقة اجتماعية، إحساس بالإلحاح عند الاقتضاء، ضمانات واضحة (خصوصاً الدفع عند الاستلام)،
وأسئلة شائعة تبدد شكوك الزبون قبل الطلب).

منتج: {name}
وصف التاجر: {description or 'غير محدد'}
معلومات إضافية زوّدها التاجر:
{answers_text or 'لا توجد'}

ابنيلي محتوى صفحة الهبوط بصيغة JSON فقط (بلا أي نص إضافي قبلها أو بعدها)، بهذا الشكل بالضبط:
{{
  "headline": "عنوان قوي وجذاب (سطر واحد قصير)",
  "subheadline": "جملة ثانية توضح الفائدة الرئيسية (قصيرة)",
  "description": "وصف تسويقي مُعاد صياغته (3-5 أسطر)",
  "benefits": ["فائدة 1 مع إيموجي مناسب", "فائدة 2", "فائدة 3", "فائدة 4"],
  "urgencyText": "جملة قصيرة تخلق إحساس بالإلحاح إذا سمحت المعلومات المزوّدة بذلك، وإلا اتركها فارغة",
  "guaranteeText": "جملة ضمان (دفع عند الاستلام / استرجاع...) إذا زوّد التاجر معلومات، وإلا اتركها فارغة",
  "faq": [{{"q":"سؤال شائع 1","a":"جواب قصير"}}, {{"q":"سؤال شائع 2","a":"جواب قصير"}}, {{"q":"سؤال شائع 3","a":"جواب قصير"}}]
}}
استعمل نفس لغة الوصف الأصلي (عربي أو فرنسي أو دارجة)، ولا تخترع معلومات غير موجودة (مثلاً لا تذكر مدة استرجاع محددة إذا التاجر ما زوّدهاش)."""
        contents = [types.Part.from_text(text=prompt)]
        cfg = types.GenerateContentConfig(temperature=0.6, max_output_tokens=900)
        text, _ = _gemini_generate_with_fallback(api_key, contents, cfg, "landing_copy_full")
        cleaned = text.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            for key in ("headline", "subheadline", "description", "urgencyText", "guaranteeText"):
                if parsed.get(key):
                    fallback[key] = str(parsed[key])[:400]
            if isinstance(parsed.get("benefits"), list):
                fallback["benefits"] = [str(b)[:120] for b in parsed["benefits"] if str(b or "").strip()][:6]
            if isinstance(parsed.get("faq"), list):
                faq = []
                for item in parsed["faq"][:5]:
                    if isinstance(item, dict) and item.get("q") and item.get("a"):
                        faq.append({"q": str(item["q"])[:150], "a": str(item["a"])[:300]})
                fallback["faq"] = faq
    except Exception as e:
        logging.warning(f"landing/generate: تعذّر توليد محتوى كامل عبر Gemini، استُعمل fallback بسيط: {e}")
    return fallback


def _build_landing_html(uid, page):
    """يبني صفحة هبوط HTML عامة. كل قيمة نصية غير ثابتة تمر عبر _esc() قبل الإدراج —
    بما فيها روابط الصور (images) و og:image، لمنع Stored XSS يطال زوّار الصفحة."""
    store    = _fb_get(f"data/{uid}/storeSettings") or {}
    store_name = store.get("name", "Boutique")
    images   = [img for img in (page.get("images") or []) if _sanitize_image_url(img)]
    imgs_html = "".join(
        f'<div class="lp-slide{" active" if i == 0 else ""}"><img src="{_esc(img)}" loading="lazy" alt=""/></div>'
        for i, img in enumerate(images)
    ) or '<div class="lp-slide active lp-noimg">📦</div>'
    dots_html = "".join(
        f'<span class="lp-dot{" active" if i == 0 else ""}" data-i="{i}"></span>' for i in range(len(images))
    )
    gallery_pill = (
        f'<div class="lp-gallery-pill"><span class="lp-gallery-dots">{dots_html}</span>'
        f'<span class="lp-gallery-count">1/{len(images)}</span></div>'
        if len(images) > 1 else ""
    )

    cta_type = page.get("ctaType", "store")
    if cta_type == "whatsapp":
        wa_number  = re.sub(r"\D", "", page.get("whatsappNumber", ""))
        wa_text    = quote(f"مرحباً، أريد أطلب: {page.get('name','')}")
        cta_href   = f"https://wa.me/{wa_number}?text={wa_text}"
        cta_label  = "💬 اطلب عبر واتساب"
        cta_target = ' target="_blank" rel="noopener"'
    else:
        cta_href   = f"/?store={uid}"
        cta_label  = "🛍️ اطلب الآن من المتجر"
        cta_target = ""

    name         = _esc(page.get("name", ""))
    headline     = _esc(page.get("headline") or page.get("name", ""))
    subheadline  = _esc(page.get("subheadline", ""))
    desc_raw     = page.get("description", "") or ""
    desc_html    = _esc(desc_raw).replace("\n", "<br/>")
    desc_meta    = re.sub(r"\s+", " ", desc_raw)[:150]
    benefits     = [b for b in (page.get("benefits") or []) if str(b or "").strip()]
    urgency_text = str(page.get("urgencyText") or "").strip()
    guarantee    = str(page.get("guaranteeText") or "").strip()
    faq          = [f for f in (page.get("faq") or []) if isinstance(f, dict) and f.get("q") and f.get("a")]

    urgency_html = (
        f'<div class="lp-urgency"><span class="lp-pulse-dot"></span>{_esc(urgency_text)}</div>'
        if urgency_text else ""
    )

    benefits_html = ""
    if benefits:
        items = "".join(
            f'<div class="lp-benefit"><span class="lp-benefit-ico">✓</span><span>{_esc(b)}</span></div>'
            for b in benefits
        )
        benefits_html = f'<div class="lp-section"><div class="lp-benefits">{items}</div></div>'

    guarantee_html = (
        f'<div class="lp-guarantee"><span class="lp-guarantee-ico">🛡️</span>{_esc(guarantee)}</div>'
        if guarantee else ""
    )

    faq_html = ""
    if faq:
        rows = "".join(
            f'<details class="lp-faq-item"><summary><span>{_esc(f["q"])}</span>'
            f'<span class="lp-faq-plus"></span></summary>'
            f'<p>{_esc(f["a"])}</p></details>'
            for f in faq
        )
        faq_html = f'<div class="lp-section"><h2 class="lp-h2">أسئلة شائعة</h2>{rows}</div>'

    subheadline_html = f'<p class="lp-sub">{subheadline}</p>' if subheadline else ""

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{name} — {_esc(store_name)}</title>
<meta name="description" content="{_esc(desc_meta)}"/>
<meta property="og:title" content="{name}"/>
<meta property="og:description" content="{_esc(desc_meta)}"/>
{f'<meta property="og:image" content="{_esc(images[0])}"/>' if images else ''}
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@700;800;900&family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet"/>
<style>
:root{{
  --accent:#3b82f6; --accent2:#7dd3fc; --amber:#fbbf24; --good:#22c55e;
  --bg:#070c18; --bg2:#0d1b2e; --text:#eef2fb; --muted:#94a3c4;
  --glass:rgba(255,255,255,.05); --glass-bd:rgba(255,255,255,.10);
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{background:var(--bg)}}
body{{
  font-family:'Tajawal',Arial,sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;overflow-x:hidden;position:relative;
}}
.lp-glow{{position:fixed;border-radius:50%;filter:blur(70px);opacity:.35;z-index:0;pointer-events:none}}
.lp-glow-a{{width:340px;height:340px;background:var(--accent);top:-120px;right:-90px}}
.lp-glow-b{{width:300px;height:300px;background:var(--amber);bottom:10%;left:-110px;opacity:.18}}
.lp-page{{position:relative;z-index:1;max-width:520px;margin:0 auto;padding-bottom:112px}}

.lp-urgency{{display:flex;align-items:center;justify-content:center;gap:8px;
  background:linear-gradient(90deg,#7f1d1d,#b91c1c 55%,#dc2626);color:#fff;text-align:center;
  font-size:12.5px;font-weight:700;padding:10px 14px;letter-spacing:.2px}}
.lp-pulse-dot{{width:7px;height:7px;border-radius:50%;background:#fff;flex:none;
  animation:lpPulse 1.4s ease-in-out infinite}}
@keyframes lpPulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.35;transform:scale(1.6)}}}}

.lp-eyebrow{{display:flex;justify-content:center;padding:18px 20px 0}}
.lp-eyebrow span{{background:var(--glass);border:1px solid var(--glass-bd);backdrop-filter:blur(8px);
  color:var(--accent2);font-size:11.5px;font-weight:700;padding:6px 14px;border-radius:999px;letter-spacing:.2px}}

.lp-stage{{padding:22px 26px 46px;perspective:1400px}}
.lp-card-3d{{
  position:relative;border-radius:26px;overflow:hidden;
  border:1px solid rgba(255,255,255,.12);
  box-shadow:0 40px 70px -24px rgba(59,130,246,.55), 0 16px 30px -12px rgba(0,0,0,.65),
    inset 0 1px 0 rgba(255,255,255,.08);
  transform:rotateX(6deg) rotateY(-7deg);
  animation:lpFloat 5.5s ease-in-out infinite;
  background:var(--bg2);
}}
@keyframes lpFloat{{
  0%,100%{{transform:rotateX(6deg) rotateY(-7deg) translateY(0)}}
  50%{{transform:rotateX(3deg) rotateY(-3deg) translateY(-10px)}}
}}
.lp-slider{{position:relative;width:100%;height:360px;overflow:hidden;background:var(--bg2)}}
.lp-slide{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .5s ease}}
.lp-slide.active{{opacity:1}}
.lp-slide img{{width:100%;height:100%;object-fit:cover}}
.lp-noimg{{font-size:80px;opacity:.3}}

.lp-gallery-pill{{position:absolute;left:50%;bottom:-19px;transform:translateX(-50%);
  display:flex;align-items:center;gap:10px;background:rgba(13,27,46,.85);border:1px solid var(--glass-bd);
  backdrop-filter:blur(10px);border-radius:999px;padding:7px 14px;
  box-shadow:0 10px 24px -8px rgba(0,0,0,.6);z-index:2}}
.lp-gallery-dots{{display:flex;gap:5px}}
.lp-dot{{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.25)}}
.lp-dot.active{{background:var(--accent2)}}
.lp-gallery-count{{font-size:10.5px;color:var(--muted);font-weight:700}}

.lp-body{{padding:14px 22px 0}}
.lp-headline{{font-family:'Cairo',sans-serif;font-weight:900;font-size:25px;line-height:1.42;
  letter-spacing:-.01em;margin-bottom:8px;
  background:linear-gradient(90deg,#ffffff,var(--accent2));-webkit-background-clip:text;
  background-clip:text;-webkit-text-fill-color:transparent}}
.lp-sub{{font-size:14.5px;color:var(--accent2);font-weight:700;margin-bottom:14px}}
.lp-body p{{font-size:14px;color:var(--muted);line-height:1.85}}

.lp-guarantee{{margin-top:18px;display:flex;align-items:center;gap:9px;
  background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);color:var(--good);
  border-radius:14px;padding:12px 15px;font-size:13px;font-weight:700;
  box-shadow:0 10px 22px -14px rgba(34,197,94,.6)}}
.lp-guarantee-ico{{font-size:16px;flex:none}}

.lp-section{{padding:26px 22px 0}}
.lp-h2{{font-family:'Cairo',sans-serif;font-size:16.5px;font-weight:800;margin-bottom:12px}}

.lp-benefits{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.lp-benefit{{display:flex;align-items:flex-start;gap:8px;background:var(--glass);border:1px solid var(--glass-bd);
  backdrop-filter:blur(10px);border-radius:14px;padding:12px 12px;font-size:12.8px;line-height:1.5;
  box-shadow:0 12px 24px -18px rgba(0,0,0,.7)}}
.lp-benefit-ico{{flex:none;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:900;color:#04101f;
  background:linear-gradient(135deg,var(--accent2),var(--accent))}}

.lp-faq-item{{background:var(--glass);border:1px solid var(--glass-bd);backdrop-filter:blur(10px);
  border-radius:14px;padding:14px 16px;margin-bottom:9px;box-shadow:0 12px 24px -18px rgba(0,0,0,.7)}}
.lp-faq-item summary{{cursor:pointer;font-size:13.5px;font-weight:700;list-style:none;
  display:flex;align-items:center;justify-content:space-between;gap:10px}}
.lp-faq-item summary::-webkit-details-marker{{display:none}}
.lp-faq-plus{{flex:none;width:20px;height:20px;border-radius:50%;background:rgba(59,130,246,.18);
  color:var(--accent2);position:relative}}
.lp-faq-plus::before,.lp-faq-plus::after{{content:"";position:absolute;background:var(--accent2);
  top:50%;left:50%;transform:translate(-50%,-50%)}}
.lp-faq-plus::before{{width:9px;height:2px}}
.lp-faq-plus::after{{width:2px;height:9px;transition:transform .2s ease}}
.lp-faq-item[open] .lp-faq-plus::after{{transform:translate(-50%,-50%) rotate(90deg) scaleY(0)}}
.lp-faq-item p{{margin-top:9px;font-size:12.8px;color:var(--muted);line-height:1.75}}

.lp-brand{{text-align:center;padding:30px 10px 6px;font-size:11px;color:var(--muted);letter-spacing:.3px}}

.lp-cta-fixed{{position:fixed;bottom:0;left:0;right:0;z-index:5;padding:14px 20px 18px;
  background:linear-gradient(180deg,rgba(7,12,24,0),rgba(7,12,24,.92) 35%,var(--bg))}}
.lp-cta-inner{{max-width:520px;margin:0 auto}}
.lp-cta-btn{{display:block;width:100%;text-align:center;padding:15px;border-radius:14px;
  font-weight:800;font-size:15.5px;text-decoration:none;color:#04101f;
  background:linear-gradient(135deg,var(--accent2),var(--accent));
  box-shadow:0 16px 34px -12px rgba(59,130,246,.75), inset 0 1px 0 rgba(255,255,255,.5);
  animation:lpGlow 2.6s ease-in-out infinite}}
@keyframes lpGlow{{
  0%,100%{{box-shadow:0 16px 34px -12px rgba(59,130,246,.75), inset 0 1px 0 rgba(255,255,255,.5)}}
  50%{{box-shadow:0 16px 44px -8px rgba(59,130,246,1), inset 0 1px 0 rgba(255,255,255,.6)}}
}}
@media (prefers-reduced-motion: reduce){{
  .lp-card-3d,.lp-cta-btn,.lp-pulse-dot{{animation:none}}
}}
</style>
</head>
<body>
<div class="lp-glow lp-glow-a"></div>
<div class="lp-glow lp-glow-b"></div>
<div class="lp-page">
  {urgency_html}
  <div class="lp-eyebrow"><span>🛍️ {_esc(store_name)}</span></div>
  <div class="lp-stage">
    <div class="lp-card-3d">
      <div class="lp-slider" id="lpSlider">{imgs_html}</div>
      {gallery_pill}
    </div>
  </div>
  <div class="lp-body">
    <h1 class="lp-headline">{headline}</h1>
    {subheadline_html}
    <p>{desc_html}</p>
    {guarantee_html}
  </div>
  {benefits_html}
  {faq_html}
  <div class="lp-brand">{_esc(store_name)} — {name}</div>
</div>
<div class="lp-cta-fixed"><div class="lp-cta-inner">
  <a class="lp-cta-btn" href="{cta_href}"{cta_target}>{cta_label}</a>
</div></div>
<script>
(function(){{
  var slides = document.querySelectorAll('.lp-slide');
  var dots   = document.querySelectorAll('.lp-dot');
  var countEl = document.querySelector('.lp-gallery-count');
  var idx = 0;
  function show(i){{
    slides.forEach(function(s,j){{ s.classList.toggle('active', j===i); }});
    dots.forEach(function(d,j){{ d.classList.toggle('active', j===i); }});
    if(countEl) countEl.textContent = (i+1) + '/' + slides.length;
    idx = i;
  }}
  dots.forEach(function(d){{ d.addEventListener('click', function(){{ show(parseInt(d.dataset.i)); }}); }});
  if(slides.length>1){{ setInterval(function(){{ show((idx+1)%slides.length); }}, 4000); }}
}})();
</script>
</body>
</html>"""
