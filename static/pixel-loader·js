/* pixel-loader.js — يُحمَّل فقط بصفحة المتجر العامة (initShop)
   يقرأ إعدادات التتبع من /api/tracking/public ويحقن fbq/ttq/gtag ديناميكياً.
   لا يلمس أي كود موجود — بس يضيف <script defer src="/static/pixel-loader.js">
   واحد بـ <head> صفحة index.html. */
(function(){
  function getStoreUid(){
    var p = new URLSearchParams(window.location.search);
    return p.get("store");
  }

  function loadMetaPixel(id){
    if(window.fbq) return;
    !function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
    n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
    n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
    t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
    document,'script','https://connect.facebook.net/en_US/fbevents.js');
    fbq('init', id);
    fbq('track', 'PageView');
  }

  function loadTikTokPixel(id){
    if(window.ttq) return;
    !function(w, d, t) {
      w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie"],ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e},ttq.load=function(e,n){var i="https://analytics.tiktok.com/i18n/pixel/events.js";ttq._i=ttq._i||{},ttq._i[e]=[],ttq._i[e]._u=i,ttq._t=ttq._t||{},ttq._t[e]=+new Date,ttq._o=ttq._o||{},ttq._o[e]=n||{};var o=document.createElement("script");o.type="text/javascript",o.async=!0,o.src=i+"?sdkid="+e+"&lib="+t;var a=document.getElementsByTagName("script")[0];a.parentNode.insertBefore(o,a)};
      ttq.load(id);
      ttq.page();
    }(window, document, 'ttq');
  }

  function loadGoogleAds(id){
    if(window.gtag) { gtag('config', id); return; }
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + id;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function(){ dataLayer.push(arguments); };
    gtag('js', new Date());
    gtag('config', id);
  }

  function loadSnapPixel(id){
    if(window.snaptr) return;
    (function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function(){a.handleRequest?
    a.handleRequest.apply(a,arguments):a.queue.push(arguments)};a.queue=[];var s='script';
    var r=t.createElement(s);r.async=!0;r.src=n;var u=t.getElementsByTagName(s)[0];
    u.parentNode.insertBefore(r,u)})(window,document,
    'https://sc-static.net/scevent.min.js');
    snaptr('init', id);
    snaptr('track', 'PAGE_VIEW');
  }

  var uid = getStoreUid();
  if(!uid) return;

  fetch("/api/tracking/public?userId=" + encodeURIComponent(uid))
    .then(function(r){ return r.json(); })
    .then(function(res){
      if(res.status !== "ok") return;
      var d = res.data || {};
      if(d.metaPixelId) loadMetaPixel(d.metaPixelId);
      if(d.tiktokPixelId) loadTikTokPixel(d.tiktokPixelId);
      if(d.googleAdsId) loadGoogleAds(d.googleAdsId);
      if(d.googleAnalyticsId) loadGoogleAds(d.googleAnalyticsId);
      if(d.snapPixelId) loadSnapPixel(d.snapPixelId);
    })
    .catch(function(){});

  /* دالة عامة تُستدعى من نقاط الشراء الموجودة (سطر واحد بكل نقطة):
     trackShopEvent('AddToCart', {content_name:'...', value:..., currency:'DZD'}) */
  window.trackShopEvent = function(eventName, params){
    try{
      if(window.fbq) fbq('track', eventName, params||{});
      if(window.ttq) ttq.track(eventName, params||{});
      if(window.gtag) gtag('event', eventName, params||{});
      if(window.snaptr) snaptr('track', eventName, params||{});
    }catch(e){}
  };
})();