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
from core.templates import render
from markupsafe import Markup


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

    return render("landing.html",
        name=Markup(name),
        store_name=store_name,
        desc_meta=desc_meta,
        og_image_meta=Markup(f'<meta property="og:image" content="{_esc(images[0])}"/>' if images else ''),
        urgency_html=Markup(urgency_html),
        imgs_html=Markup(imgs_html),
        gallery_pill=Markup(gallery_pill),
        headline=Markup(headline),
        subheadline_html=Markup(subheadline_html),
        desc_html=Markup(desc_html),
        guarantee_html=Markup(guarantee_html),
        benefits_html=Markup(benefits_html),
        faq_html=Markup(faq_html),
        cta_href=Markup(cta_href),
        cta_target=Markup(cta_target),
        cta_label=Markup(cta_label),
    )
