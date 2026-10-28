// =========================================================
// PUBLIC SHOP — متجر عام (بدون مصادقة، عبر المسارات العامة فقط)
// =========================================================
var SHOP_PRODUCTS = [];
var SHOP_CITIES   = [];
var SHOP_CART     = [];
var SHOP_CURRENCY = "DZD";
var SHOP_CATEGORY = "";
var PDP_PRODUCT   = null;
var PDP_SLIDER    = null;

(function(){
  var p = new URLSearchParams(window.location.search);
  var s = p.get("store");
  if(s){
    SHOP_UID = s;
    initShop();
  }
})();

function initShop(){
  // shop.html ما فيهاش صفحة الدخول (كانت مخفية هنا ملي كان المتجر داخل index.html)
  document.getElementById("loginPage") && (document.getElementById("loginPage").style.display = "none");
  document.getElementById("shopApp").style.display    = "block";
  document.getElementById("sidebar") && (document.getElementById("sidebar").style.display="none");
  document.getElementById("main")    && (document.getElementById("main").style.display="none");
  document.body.style.display = "block";
  loadShopData();
  document.getElementById("sh-search").addEventListener("input", function(){ sh_renderGrid(this.value); });
}

async function loadShopData(){
  try{
    var sr = await apiGet("/getStoreSettings", {userId: SHOP_UID}, false);
    if(sr.status==="ok" && sr.data && sr.data.storeOpen===false){
      // store_unavailable: باقة المتجر ما فيهاش متجر عام (free أو اشتراك انتهى) — ما نطلبوش المنتجات
      document.getElementById("sh-loading").style.display = "none";
      var empty = document.getElementById("sh-empty");
      empty.style.display = "block";
      empty.textContent = "هذا المتجر غير متاح حالياً";
      if(sr.data.name) document.getElementById("sh-name").textContent = sr.data.name;
      return;
    }
    var pr = await apiGet("/getStoreProducts", {userId: SHOP_UID}, false);
    var cr = await apiGet("/getStoreCities",   {userId: SHOP_UID}, false);

    SHOP_PRODUCTS = (pr.status==="ok" && pr.data) ? pr.data.filter(function(p){ return p.visible!=="no"; }) : [];
    SHOP_CITIES   = (cr.status==="ok" && cr.data) ? cr.data : [];

    if(sr.status==="ok" && sr.data){
      var s = sr.data;
      SHOP_CURRENCY = s.currency || "DZD";
      sh_applyColor(s.color);
      var storeName = s.name||"Boutique";
      sh_renderLogo(document.getElementById("sh-logo"), s.logoImage, storeName);
      sh_renderLogo(document.getElementById("track-logo"), s.logoImage, storeName);
      sh_setFavicon(s.logoImage, storeName);
      document.getElementById("sh-name").textContent = storeName;
      document.getElementById("track-name").textContent = storeName;
      document.getElementById("sh-tag").textContent  = s.tagline||"Catalogue en ligne";
      var pageTitle = (s.name||"Boutique")+" — "+(s.tagline||"OrderFlow");
      document.title = pageTitle;
      sh_setMeta("description", s.tagline || ("متجر "+(s.name||"")+" — تسوّق الآن"));
      sh_setMeta("og:title", pageTitle, true);
    }

    var citySel = document.getElementById("sh-ccity");
    citySel.innerHTML = '<option value="">— Choisir la ville —</option>'+
      SHOP_CITIES.map(function(c){ return '<option value="'+esc(c.name)+'" data-home-ship="'+esc(c.custShip||0)+'" data-desk-ship="'+esc(c.deskCust||0)+'">'+esc(c.name)+'</option>'; }).join("");
    citySel.addEventListener("change", sh_updateTotal);
    document.getElementById("sh-delivery").addEventListener("change", sh_updateTotal);

    sh_renderCategories();
    document.getElementById("sh-loading").style.display = "none";
    sh_renderGrid("");
  }catch(e){
    document.getElementById("sh-loading").style.display = "none";
    document.getElementById("sh-empty").style.display   = "block";
    console.error(e);
  }
}

// ── شعار المتجر (D4a): الصورة، ولا أول حرف من الاسم فمربع بلون المتجر.
// الإيموجي القديم (storeSettings.logo) يبقى فالبيانات وما يبانش هنا.
var SHOP_COLOR_MAIN = "#3B2BFF";

// ── لون المتجر (D4a): المفتاح من storeSettings.color → (أساسي، فاتح) من هاد الجدول الثابت
// (نفس STORE_COLORS فـ core/config.py). قيمة السيرفر ما تدخلش للـ CSS مباشرة؛ غير معروف = violet.
var SHOP_COLORS = {
  violet:["#3B2BFF","#E6E3FF"], blue:["#1D4ED8","#DBEAFE"], emerald:["#0F766E","#CCFBF1"],
  orange:["#C2410C","#FFEDD5"], pink:["#BE123C","#FFE4E6"], mauve:["#7C3AED","#EDE9FE"]
};

function sh_applyColor(key){
  var c = Object.prototype.hasOwnProperty.call(SHOP_COLORS, key) ? SHOP_COLORS[key] : SHOP_COLORS.violet;
  document.body.style.setProperty("--store", c[0]);
  document.body.style.setProperty("--store-light", c[1]);
  SHOP_COLOR_MAIN = c[0];
}

function sh_initial(name){
  return Array.from(String(name||"").trim())[0] || "?";  // Array.from: حرف عربي ولا إيموجي كامل
}

function sh_renderLogo(el, logoImage, name){
  el.classList.toggle("has-img", !!logoImage);
  el.innerHTML = logoImage
    ? '<img src="'+esc(logoImage)+'" alt="'+esc(name)+'"/>'
    : esc(sh_initial(name));
}

function sh_setFavicon(logoImage, name){
  var href = logoImage;
  if(!href){
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'+
      '<rect width="64" height="64" rx="16" fill="'+SHOP_COLOR_MAIN+'"/>'+
      '<text x="32" y="43" text-anchor="middle" font-family="Readex Pro,Arial,sans-serif" font-size="32" font-weight="700" fill="#fff">'+
      esc(sh_initial(name))+'</text></svg>';
    href = "data:image/svg+xml,"+encodeURIComponent(svg);
  }
  Array.prototype.forEach.call(document.querySelectorAll('link[rel~="icon"],link[rel="apple-touch-icon"]'), function(l){
    l.parentNode.removeChild(l);
  });
  var link = document.createElement("link");
  link.rel = "icon";
  link.href = href;
  document.head.appendChild(link);
}

function sh_setMeta(name, content, isProp){
  var attr = isProp ? "property" : "name";
  var el = document.querySelector('meta['+attr+'="'+name+'"]');
  if(!el){
    el = document.createElement("meta");
    el.setAttribute(attr, name);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function sh_renderCategories(){
  var cats = [];
  SHOP_PRODUCTS.forEach(function(p){ if(p.category && cats.indexOf(p.category)===-1) cats.push(p.category); });
  var box = document.getElementById("sh-categories");
  var toolbar = document.getElementById("sh-toolbar");
  if(!cats.length){ toolbar.style.display="none"; return; }
  toolbar.style.display = "flex";
  box.innerHTML = '<span class="shop-chip'+(SHOP_CATEGORY===""?" active":"")+'" data-cat="" data-on-click="sh_filterCategory(this.dataset.cat)">الكل</span>' +
    cats.map(function(c){
      return '<span class="shop-chip'+(SHOP_CATEGORY===c?" active":"")+'" data-cat="'+esc(c)+'" data-on-click="sh_filterCategory(this.dataset.cat)">'+esc(c)+'</span>';
    }).join("");
}

function sh_filterCategory(cat){
  SHOP_CATEGORY = cat;
  sh_renderCategories();
  sh_renderGrid(document.getElementById("sh-search").value);
}

function toggleTrackPanel(){
  document.getElementById("track-panel").classList.toggle("open");
}

var TRACK_PHONE = "";

async function sh_trackOrder(){
  var phone = document.getElementById("track-phone").value.trim();
  var resBox = document.getElementById("track-results");
  if(!phone){ resBox.innerHTML = '<div class="track-result">أدخل رقم الهاتف</div>'; return; }
  TRACK_PHONE = phone;
  resBox.innerHTML = '<div class="track-result"><span class="spinner"></span></div>';
  try{
    var r = await apiGet("/trackOrder", {userId: SHOP_UID, phone: phone}, false);
    if(r.status==="ok" && r.data && r.data.length){
      resBox.innerHTML = r.data.map(function(o){
        var stCls = {Pending:"bp",Confirmed:"bc",Delivered:"bi",Refused:"br","No Answer":"bn"}[o.status]||"bp";
        var rateBlock = "";
        if(o.status==="Delivered"){
          if(o.rated){
            rateBlock = '<div style="font-size:11px;color:var(--green);margin-top:6px">✅ تم تقييم هذا الطلب، شكراً لك</div>';
          } else {
            rateBlock = '<div class="rate-widget" data-order-id="'+esc(o.id)+'">'+
              '<div style="font-size:12px;margin-bottom:6px">⭐ قيّم هذا المنتج:</div>'+
              '<div class="rate-stars" data-value="0">'+
                [1,2,3,4,5].map(function(n){ return '<span data-n="'+n+'" data-on-click="setRateStar(this,parseInt(this.dataset.n))">☆</span>'; }).join("")+
              '</div>'+
              '<textarea class="rate-comment" placeholder="تعليق (اختياري)"></textarea>'+
              '<button class="btn-primary btn-sm" style="margin-top:8px" data-on-click="submitProductRating(this.closest(\'.rate-widget\').dataset.orderId,this)">إرسال التقييم</button>'+
            '</div>';
          }
        }
        return '<div class="track-result"><div style="display:flex;justify-content:space-between;align-items:center">'+
          '<div><strong>'+esc(o.product)+'</strong> × '+esc(o.qty)+'<div style="font-size:11px;color:var(--muted)">'+esc(o.date)+'</div></div>'+
          '<span class="badge '+stCls+'">'+esc(stLabel(o.status))+'</span></div>'+rateBlock+'</div>';
      }).join("");
    } else {
      resBox.innerHTML = '<div class="track-result">لا توجد طلبات بهذا الرقم</div>';
    }
  }catch(e){ resBox.innerHTML = '<div class="track-result">خطأ، حاول مرة أخرى</div>'; }
}
     

function setRateStar(el, value){
  var wrap = el.parentElement;
  wrap.setAttribute("data-value", value);
  Array.prototype.forEach.call(wrap.children, function(span, i){
    if(i < value){ span.textContent = "★"; span.classList.add("filled"); }
    else { span.textContent = "☆"; span.classList.remove("filled"); }
  });
}

async function submitProductRating(orderId, btnEl){
  var widget = btnEl.closest(".rate-widget");
  var value  = parseInt(widget.querySelector(".rate-stars").getAttribute("data-value")) || 0;
  var comment= widget.querySelector(".rate-comment").value.trim();
  if(value < 1){ toast("اختر عدد النجوم أولاً","err"); return; }
  btnEl.disabled = true;
  try{
    var r = await apiPost("/submitRating", {
      userId: SHOP_UID, orderId: orderId, phone: TRACK_PHONE, rating: value, comment: comment
    }, false);
    if(r.status==="ok"){
      widget.outerHTML = '<div style="font-size:11px;color:var(--green);margin-top:6px">✅ شكراً، تم إرسال تقييمك</div>';
      toast("✅ شكراً على تقييمك","ok");
    } else {
      toast("❌ "+r.message,"err");
      btnEl.disabled = false;
    }
  }catch(e){ toast("خطأ، حاول مرة أخرى","err"); btnEl.disabled = false; }
}

function sh_cur(){ return CURRENCY_SYMBOLS_PUBLIC[SHOP_CURRENCY] || esc(SHOP_CURRENCY); }

function starsHtml(avg, count){
  if(!count) return "";
  var full = Math.round(avg);
  var s = "";
  for(var i=1;i<=5;i++) s += (i<=full ? "★" : "☆");
  return '<div class="stars-display">'+s+' <span style="color:var(--muted);font-weight:400">('+count+')</span></div>';
}
var CURRENCY_SYMBOLS_PUBLIC = {DZD:"دج", EUR:"€", USD:"$"};

function sh_sortList(list){
  var sort = (document.getElementById("sh-sort")||{}).value || "default";
  var copy = list.slice();
  if(sort==="price_asc")  copy.sort(function(a,b){ return (a.sell||0)-(b.sell||0); });
  if(sort==="price_desc") copy.sort(function(a,b){ return (b.sell||0)-(a.sell||0); });
  if(sort==="newest")     copy.sort(function(a,b){ return (b.created_at||0)-(a.created_at||0); });
  if(sort==="bestselling")copy.sort(function(a,b){ return (b.sold||0)-(a.sold||0); });
  return copy;
}

// ── سلايدر صور المنتجات (D4a): Swiper بـ fade كل 3 ثوان، نقاط، سحب بالإصبع.
// صورة وحدة = <img> عادي. reduced-motion = بلا تبديل تلقائي (السحب والنقاط يبقاو).
// Swiper ما تحمّلش (CDN) → الصورة الأولى تبان برك.
var SH_REDUCED   = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
var SH_SLIDERS   = [];
var SH_SLIDER_IO = ("IntersectionObserver" in window) ? new IntersectionObserver(function(entries){
  // البطاقات اللي برّا الشاشة ما تتبدّلش
  entries.forEach(function(en){
    var el = en.target, sw = el.swiper;
    clearTimeout(el._shTimer);
    if(!sw || sw.destroyed) return;
    if(en.isIntersecting) el._shTimer = setTimeout(function(){ if(!sw.destroyed) sw.autoplay.start(); }, el._shDelay||0);
    else sw.autoplay.stop();
  });
}, {threshold:0.25}) : null;

function sh_images(p){
  var imgs = (p.images && p.images.length) ? p.images : (p.image ? [p.image] : []);
  return imgs.filter(Boolean).slice(0, 5);
}

function sh_mediaHtml(p){
  var imgs = sh_images(p);
  var alt  = esc(p.name||"");
  if(!imgs.length) return '📦';
  if(imgs.length===1){
    return '<img src="'+esc(imgs[0])+'" alt="'+alt+'" loading="lazy" decoding="async" data-on-error="this.style.display=\'none\'"/>';
  }
  return '<div class="swiper sh-slider"><div class="swiper-wrapper">'+
    imgs.map(function(u, i){
      return '<div class="swiper-slide"><img src="'+esc(u)+'" alt="'+alt+' ('+(i+1)+'/'+imgs.length+')" loading="lazy" decoding="async"/></div>';
    }).join("")+
    '</div><div class="swiper-pagination"></div></div>';
}

function sh_makeSlider(el, stopOnTouch){
  if(typeof Swiper==="undefined") return null;
  var pag = el.querySelector(".swiper-pagination");
  pag.addEventListener("click", function(e){ e.stopPropagation(); });  // النقطة تبدّل الصورة، ما تفتحش المنتج
  return new Swiper(el, {
    effect:"fade", fadeEffect:{crossFade:true}, rewind:true,
    speed: SH_REDUCED ? 0 : 600,
    autoplay: SH_REDUCED ? false : {delay:3000, disableOnInteraction:!!stopOnTouch},
    pagination:{el:pag, clickable:true}
  });
}

function sh_initSliders(root){
  Array.prototype.forEach.call(root.querySelectorAll(".sh-slider"), function(el, i){
    var sw = sh_makeSlider(el, false);
    if(!sw) return;
    SH_SLIDERS.push(sw);
    if(SH_REDUCED || !SH_SLIDER_IO) return;
    sw.autoplay.stop();
    el._shDelay = (i * 800) % 3000;  // نفس الدورة، بداية مختلفة لكل منتج
    SH_SLIDER_IO.observe(el);
  });
}

function sh_destroySliders(){
  SH_SLIDERS.forEach(function(sw){
    if(sw.el){ clearTimeout(sw.el._shTimer); if(SH_SLIDER_IO) SH_SLIDER_IO.unobserve(sw.el); }
    if(!sw.destroyed) sw.destroy(true, false);
  });
  SH_SLIDERS = [];
}

function sh_renderGrid(q){
  q = (q||"").toLowerCase().trim();
  var grid  = document.getElementById("sh-grid");
  var empty = document.getElementById("sh-empty");
  var list  = SHOP_PRODUCTS.filter(function(p){
    var matchQ   = !q || (p.name||"").toLowerCase().includes(q) || (p.category||"").toLowerCase().includes(q);
    var matchCat = !SHOP_CATEGORY || p.category===SHOP_CATEGORY;
    return matchQ && matchCat;
  });
  list = sh_sortList(list);
  sh_destroySliders();
  if(!list.length){ grid.innerHTML=""; empty.style.display="block"; return; }
  empty.style.display="none";
  grid.innerHTML = list.map(function(p){
    var av  = Number(p.available||0);
    var dis = av<=0;
    return '<div class="shop-card" data-name="'+esc(p.name)+'" data-on-click="pdp_open(this.dataset.name)" style="cursor:pointer">'+
      '<div class="shop-card-img">'+sh_mediaHtml(p)+'</div>'+
      '<div class="shop-card-body">'+
        '<div class="shop-card-name">'+esc(p.name)+'</div>'+
        (p.category?'<div class="shop-card-cat">'+esc(p.category)+'</div>':'')+
        starsHtml(p.avgRating, p.ratingCount)+
        (p.description?'<div style="font-size:11px;color:var(--muted);margin-top:4px">'+esc(p.description)+'</div>':'')+
        (av>0 && av<=5?'<div style="font-size:11px;color:var(--red);font-weight:700;margin-top:4px">⚡ متبقي '+av+' قطع فقط!</div>':'')+
      '</div>'+
      '<div class="shop-card-footer">'+
        '<div class="shop-price">'+esc(p.sell||0)+' '+sh_cur()+'</div>'+
        '<button class="shop-add-btn"'+(dis?' disabled':'')+' data-name="'+esc(p.name)+'" data-on-click="event.stopPropagation();sh_addToCart(this.dataset.name)">'+
        (dis?'Rupture':'🛒 Ajouter')+'</button>'+
      '</div></div>';
  }).join("");
  sh_initSliders(grid);
}

// ── Product Detail Modal (PDP) ──────────────────────────
function pdp_open(name){
  var p = SHOP_PRODUCTS.find(function(x){ return x.name===name; });
  if(!p) return;
  PDP_PRODUCT = p;
  var av = Number(p.available||0);
  document.getElementById("pdp-cat").textContent = p.category||"";
  document.getElementById("pdp-name").textContent = p.name;
  document.getElementById("pdp-stars").innerHTML = starsHtml(p.avgRating, p.ratingCount);
  document.getElementById("pdp-price").textContent = (p.sell||0)+" "+sh_cur();
  document.getElementById("pdp-desc").textContent = p.description||"";
  document.getElementById("pdp-reviews").style.display = "none";
  document.getElementById("pdp-reviews").innerHTML = "";
  var stCls = av<=0?"br":av<=5?"bn":"bs";
  var stLbl = av<=0?"Rupture de stock":av<=5?"Stock faible":"En stock";
  var statEl = document.getElementById("pdp-stat");
  statEl.className = "badge "+stCls; statEl.textContent = stLbl;
  var urgEl = document.getElementById("pdp-urgency");
  if(av>0 && av<=5){ urgEl.style.display="block"; urgEl.textContent="⚡ متبقي "+av+" قطع فقط!"; }
  else{ urgEl.style.display="none"; }
  document.getElementById("pdp-add-btn").disabled = av<=0;
  pdp_renderImage();
  document.getElementById("pdpOverlay").classList.add("open");
}
function pdp_destroySlider(){
  if(PDP_SLIDER && !PDP_SLIDER.destroyed) PDP_SLIDER.destroy(true, false);
  PDP_SLIDER = null;
}
function pdp_renderImage(){
  pdp_destroySlider();
  var box = document.getElementById("pdp-media");
  box.innerHTML = sh_mediaHtml(PDP_PRODUCT);
  var el = box.querySelector(".sh-slider");
  if(el) PDP_SLIDER = sh_makeSlider(el, true);  // يتوقف التبديل عند أول لمسة
  Array.prototype.forEach.call(document.querySelectorAll("#pdp-img-wrap .pdp-nav"), function(b){
    b.style.display = PDP_SLIDER ? "" : "none";
  });
}
function pdp_nav(dir){
  if(!PDP_SLIDER) return;
  if(dir>0) PDP_SLIDER.slideNext(); else PDP_SLIDER.slidePrev();
}
function pdp_addToCart(){
  if(PDP_PRODUCT) sh_addToCart(PDP_PRODUCT.name);
  closePdp();
}
function closePdp(){
  document.getElementById("pdpOverlay").classList.remove("open");
  pdp_destroySlider();
}

async function pdp_toggleReviews(){
  var box = document.getElementById("pdp-reviews");
  if(box.style.display==="block"){ box.style.display="none"; return; }
  box.style.display = "block";
  box.innerHTML = '<span class="spinner"></span>';
  try{
    var r = await apiGet("/getProductRatings", {userId: SHOP_UID, product: PDP_PRODUCT.name}, false);
    var items = (r.status==="ok" && r.data) ? r.data : [];
    if(!items.length){ box.innerHTML = '<div style="color:var(--muted);font-size:12px">لا توجد تقييمات بعد</div>'; return; }
    box.innerHTML = items.map(function(it){
      var rating = Math.max(0, Math.min(5, parseInt(it.rating)||0));
      var stars = "★".repeat(rating)+"☆".repeat(5-rating);
      return '<div class="review-item">'+
        '<div class="stars-display">'+stars+'</div>'+
        (it.comment?'<div style="font-size:12px;margin-top:4px">'+esc(it.comment)+'</div>':'')+
        '<div style="font-size:10px;color:var(--muted);margin-top:4px">'+esc(it.date)+'</div>'+
      '</div>';
    }).join("");
  }catch(e){ box.innerHTML = '<div style="color:var(--red);font-size:12px">خطأ فالتحميل</div>'; }
}

function sh_addToCart(name){
  var p = SHOP_PRODUCTS.find(function(x){ return x.name===name; });
  if(!p||p.available<=0) return;
  var ex = SHOP_CART.find(function(c){ return c.name===name; });
  if(ex){ if(ex.qty<p.available) ex.qty++; else{ toast("Stock insuffisant","err"); return; } }
  else SHOP_CART.push({name:p.name,sell:Number(p.sell)||0,qty:1,available:Number(p.available||0),image:p.image||""});
  sh_updateCartUI();
  trackShopEvent('AddToCart', {content_name:name, value:p.sell, currency:SHOP_CURRENCY});
  toast("✅ Ajouté: "+name,"ok");
}

function sh_cartSubtotal(){ return SHOP_CART.reduce(function(s,c){ return s+(c.sell*c.qty); },0); }

function sh_updateCartUI(){
  var count = SHOP_CART.reduce(function(s,c){ return s+c.qty; },0);
  var cnt   = document.getElementById("sh-cart-count");
  if(count>0){ cnt.textContent=count; cnt.style.display="flex"; }
  else cnt.style.display="none";

  var items = document.getElementById("cartItems");
  if(!SHOP_CART.length){
    items.innerHTML='<div style="text-align:center;padding:40px;color:var(--muted)">Panier vide</div>';
  } else {
    items.innerHTML = SHOP_CART.map(function(c){
      var img = c.image
        ? '<img src="'+esc(c.image)+'" style="width:100%;height:100%;object-fit:cover"/>'
        : '📦';
      return '<div class="cart-item">'+
        '<div class="cart-item-img">'+img+'</div>'+
        '<div class="cart-item-info">'+
          '<div class="cart-item-name">'+esc(c.name)+'</div>'+
          '<div class="cart-item-price">'+esc(c.sell||0)+' '+sh_cur()+'</div>'+
        '</div>'+
        '<div class="cart-qty">'+
          '<button class="cart-qty-btn" data-name="'+esc(c.name)+'" data-on-click="sh_changeQty(this.dataset.name,-1)">−</button>'+
          '<span style="font-weight:700;min-width:20px;text-align:center">'+c.qty+'</span>'+
          '<button class="cart-qty-btn" data-name="'+esc(c.name)+'" data-on-click="sh_changeQty(this.dataset.name,1)">+</button>'+
        '</div>'+
        '<button data-name="'+esc(c.name)+'" data-on-click="sh_removeFromCart(this.dataset.name)" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:16px;padding:4px">🗑️</button>'+
      '</div>';
    }).join("");
  }
  document.getElementById("cartTotal").textContent = sh_cartSubtotal().toLocaleString()+" "+sh_cur();
}

function sh_changeQty(name, d){
  var item = SHOP_CART.find(function(c){ return c.name===name; });
  if(!item) return;
  item.qty += d;
  if(item.qty<=0) SHOP_CART = SHOP_CART.filter(function(c){ return c.name!==name; });
  else if(item.qty>item.available) item.qty = item.available;
  sh_updateCartUI();
}

function sh_removeFromCart(name){
  SHOP_CART = SHOP_CART.filter(function(c){ return c.name!==name; });
  sh_updateCartUI();
}

function openCart(){
  document.getElementById("cartOverlay").classList.add("open");
  document.getElementById("cartDrawer").classList.add("open");
}
function closeCart(){
  document.getElementById("cartOverlay").classList.remove("open");
  document.getElementById("cartDrawer").classList.remove("open");
}

function goCheckout(){
  trackShopEvent('InitiateCheckout', {value:sh_cartSubtotal(), currency:SHOP_CURRENCY});
  if(!SHOP_CART.length){ toast("Panier vide","err"); return; }
  closeCart();
  document.getElementById("sh-checkout-items").innerHTML = SHOP_CART.map(function(c){
    return '<div style="display:flex;justify-content:space-between;font-size:13px;padding:4px 0">'+
      '<span>'+esc(c.name)+' × '+c.qty+'</span>'+
      '<span style="font-weight:700">'+(c.sell*c.qty).toLocaleString()+' '+sh_cur()+'</span></div>';
  }).join("");
  sh_updateTotal();
  sh_goStep("checkout");
}

function sh_updateTotal(){
  var sub  = sh_cartSubtotal();
  var sel  = document.getElementById("sh-ccity");
  var dtype = document.getElementById("sh-delivery").value;
  var ship = 0;
  if(dtype && sel.selectedIndex>0){
    var attr = dtype==="desk" ? "deskShip" : "homeShip";
    ship = parseFloat(sel.options[sel.selectedIndex].dataset[attr])||0;
  }
  document.getElementById("sh-subtotal").textContent   = sub.toLocaleString()+" "+sh_cur();
  document.getElementById("sh-ship-cost").textContent  = dtype ? (ship.toLocaleString()+" "+sh_cur()) : "—";
  document.getElementById("sh-total").textContent      = dtype ? ((sub+ship).toLocaleString()+" "+sh_cur()) : "—";
}

async function sh_submitOrder(){
  var name  = document.getElementById("sh-cname").value.trim();
  var phone = document.getElementById("sh-cphone").value.trim();
  var city  = document.getElementById("sh-ccity").value;
  var addr  = document.getElementById("sh-caddr").value.trim();
  var dtype = document.getElementById("sh-delivery").value;
  if(!name||!phone||!city){ toast("Remplissez les champs *","err"); return; }
  if(!dtype){ toast("اختر نوع التوصيل (منزل أو مكتب الاستلام)","err"); return; }

  var sel  = document.getElementById("sh-ccity");
  var attr = dtype==="desk" ? "deskShip" : "homeShip";
  var ship = sel.selectedIndex>0 ? (parseFloat(sel.options[sel.selectedIndex].dataset[attr])||0) : 0;
  var lastId = null;
  var ok = true;

  for(var i=0; i<SHOP_CART.length; i++){
    var c = SHOP_CART[i];
    var r = await apiPost("/addOrder",{userId:SHOP_UID, data:{
      name:name, phone:phone, phone2:document.getElementById("sh-cphone2").value.trim(),
      product:c.name, qty:c.qty, unitPrice:c.sell, city:city, address:addr,
      deliveryType:dtype, shipping:ship, total:(c.sell*c.qty)+ship, status:"Pending", source:"store"
    }}, false);
    if(r&&r.status==="ok") lastId = r.data&&r.data.orderId;
    else ok=false;
  }

  if(ok){
    trackShopEvent('Purchase', {value:sh_cartSubtotal(), currency:SHOP_CURRENCY, content_ids:[lastId]});
    document.getElementById("sh-order-ref").textContent = lastId||"—";
    SHOP_CART = [];
    sh_updateCartUI();
    sh_goStep("success");
  } else {
    toast("❌ Erreur lors de l'envoi","err");
  }
}

function sh_goStep(step){
  ["grid","checkout","success"].forEach(function(s){
    document.getElementById("sh-step-"+s).style.display = s===step?"block":"none";
  });
  window.scrollTo(0,0);
}

