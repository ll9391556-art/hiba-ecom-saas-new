// =========================================================
// CONFIG
// =========================================================
var API_URL    = "https://orderconfidence.com/api";
var FB_BACKEND = "https://orderconfidence.com";
var FB_ORIGIN  = new URL(FB_BACKEND).origin;  // صفحة /callback تبعث postMessage غير من هنا
var FB_APP_ID_JS = "1484940433173462";
// احتياطي: trackShopEvent تتعرّف فـ /static/pixel-loader.js (defer). إذا ما تحمّلش الملف،
// السلة والدفع ما يطيحوش بـ ReferenceError — pixel-loader يستبدلها كي يتحمّل.
window.trackShopEvent = window.trackShopEvent || function(){};

var currentUser  = null;
var authToken    = localStorage.getItem("of_token") || null;
var allOrders    = [];
var allCustomers = [];
var currentLang  = localStorage.getItem("of_lang") || "FR";
var currentPlan  = "free";
var currentRole  = "owner";
var merchantCurrency = "DZD";
var BOT_LAUNCHED = false;
var PLAN_USAGE = {};
var USER_SOURCE = "local";
var LIFETIME_SLOTS_LEFT = null;
var TEAM_MEMBERS = [];
var TEAM_COUNT = 0;
var TEAM_MAX = 6;
var TEAM_PERM_KEYS = ["orders","products","customers","cities","store","bot","messages","integrations","landing"];
var CURRENCY_SYMBOLS = {DZD:"دج", EUR:"€", USD:"$"};
function curSym(){ return CURRENCY_SYMBOLS[merchantCurrency] || esc(merchantCurrency); }

function renderCurrencyButtons(){
  var box = document.getElementById("currencyButtons");
  if(!box) return;
  box.innerHTML = ["DZD","EUR","USD"].map(function(code){
    return '<button class="lang-btn'+(code===merchantCurrency?" active":"")+'" data-code="'+esc(code)+'" onclick="setMerchantCurrency(this.dataset.code)">'+esc(code)+'</button>';
  }).join("");
}

async function setMerchantCurrency(code){
  if(code===merchantCurrency) return;
  merchantCurrency = code;
  renderCurrencyButtons();
  try{
    var r = await apiPost("/updateStoreSettings", {data:{currency:code}});
    if(r.status==="ok") toast("✅ "+code,"ok");
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("Erreur réseau","err"); }
  // تحديث الأرقام المعروضة فالقسم الحالي فوراً بلا حاجة لإعادة تحميل الصفحة
  var activeSec = document.querySelector(".section.active");
  if(activeSec){
    var sec = activeSec.id.replace("sec_","");
    if(sec==="dashboard") loadDashboard();
    else if(sec==="orders") loadOrders();
    else if(sec==="products") loadProducts();
    else if(sec==="cities") loadCities();
    else if(sec==="store") loadStore();
  }
}
var _ordersPollTimer = null;

// =========================================================
// I18N
// =========================================================
var I18N = {
  FR:{
    nav_dashboard:"Tableau de bord",nav_orders:"Commandes",nav_products:"Produits",
    nav_customers:"Clients",nav_cities:"Villes",nav_store:"Boutique",nav_bot:"Bot AI",
    nav_plans:"Abonnements",nav_settings:"Paramètres",nav_discounts:"Codes promo", nav_tracking:"Suivi publicitaire",nav_shipping:"Sociétés de livraison", nav_assistant:"Assistant administratif",nav_support:"Support technique", logout:"Déconnexion",
    total_orders:"Total Commandes",confirmed:"Confirmées",refused:"Refusées",
    delivered:"Livré",total_profit:"Bénéfice Total",top_products:"Top Produits",
    low_stock:"Stock Faible",add_order:"Ajouter commande",add_product:"Ajouter produit",
    add_city:"Ajouter ville",client:"Client",phone:"Téléphone",product:"Produit",
    qty:"Qté",city:"Ville",total:"Total",profit:"Bénéfice",source:"Source",
    status:"Statut",date:"Date",sent:"Envoyé",delivered_date:"Livré le",
    address:"Adresse",notes:"Notes",add:"Ajouter",cancel:"Annuler",save:"Enregistrer",
    settings:"Paramètres",bot_settings:"Paramètres Bot",bot_logs:"Logs Bot",
    instructions:"Instructions",store_settings:"Boutique settings",
    locked_store:"Boutique non disponible",upgrade_store:"Passez au plan Starter+",
    locked_bot:"Bot AI non disponible",upgrade_bot:"Passez au plan Pro ou Full",
    see_plans:"Voir les abonnements",account:"Compte",username:"Nom d'utilisateur",
    plan:"Plan",connect_fb:"Connecter Facebook",disconnect:"Déconnecter",
    plan_contact:"Pour changer de plan, contactez l'administrateur.",
    loginTagline:"Plateforme de gestion des ventes",user:"Nom d'utilisateur",pass:"Mot de passe",login_btn:"Connexion",
    delivery_type:"Type de livraison",home_delivery:"🏠 Domicile",desk_delivery:"🏢 Bureau (Stop Desk)",
    home_section:"🏠 Livraison à domicile",desk_section:"🏢 Livraison au bureau (Stop Desk)",
    ship_cost:"Coût livraison",ship_cust:"Frais client",return_fee_shared:"Frais de retour (partagé)",
    delivery_col:"Livraison",home_short:"🏠 Domicile",desk_short:"🏢 Bureau",select_delivery:"— Choisir le type de livraison —",
    nav_integrations:"Intégrations",locked_integrations:"Intégration non disponible",upgrade_integrations:"Passez au plan Pro ou Full",
    woo_desc:"Connectez votre boutique WooCommerce, OrderFlow importera ses commandes automatiquement.",
    woo_store_url:"URL de la boutique (https://...)",woo_consumer_key:"Consumer Key",woo_consumer_secret:"Consumer Secret",
    woo_connect_btn:"Connecter la boutique",woo_connected:"Connecté",woo_sync_now:"🔄 Synchroniser maintenant",
    woo_disconnect:"Déconnecter",woo_last_sync:"Dernière synchro",
    bot_coming_soon_title:"🚀 Bientôt disponible",bot_coming_soon_desc:"Nous activons l'assistant IA officiellement (en attente de l'approbation Meta pour Instagram). Vous serez informé dès son lancement !",
    bill_monthly:"Mensuel",bill_yearly:"Annuel (économisez 2 mois)",
    pf_orders:"Gestion des commandes",pf_dashboard:"Tableau de bord",pf_store:"Boutique en ligne",pf_bot:"Bot AI",
    pf_all_starter:"Tout Starter",pf_woo:"Connexion WooCommerce",pf_all_pro:"Tout Pro",pf_vip:"Support VIP",
    pf_bot_soon:"Bot AI (bientôt)",pf_all_inclusive:"Tout inclus + WooCommerce",
    pf_bot_soon_cap:"Bot AI (3 000 messages/mois)",pf_order_cap:"300 commandes/mois max",
    pf_lifetime:"Paiement unique — à vie",
    home_cost_th:"🏠 Domicile (coût)",home_cust_th:"🏠 Domicile (client)",
    desk_cost_th:"🏢 Bureau (coût)",desk_cust_th:"🏢 Bureau (client)",
    nav_messages:"Messages",locked_messages:"Messages non disponibles",
    upgrade_messages:"Passez au plan Pro ou Full",no_conversations:"Aucune conversation",
    select_conversation:"Sélectionnez une conversation",type_message:"Écrire un message...",
    chart_status:"📊 Répartition des statuts",chart_trend:"📈 Bénéfice (7 derniers jours)",chart_topproducts:"🏆 Meilleurs produits",
    nav_team:"Équipe",add_member:"Ajouter un membre",member_username:"Nom d'utilisateur",member_name:"Nom",
    member_password:"Mot de passe",permissions:"Permissions",active:"Actif",inactive:"Inactif",
    locked_team:"Fonctionnalité Équipe non disponible",upgrade_team:"Passez au plan Starter ou supérieur",
    edit:"Modifier",delete:"Supprimer",confirm_delete_member:"Supprimer ce membre de l'équipe ?",
    team_count_of:"membre(s) sur",leave_blank_password:"Laisser vide pour ne pas changer",
    owner_only_feature:"Fonctionnalité réservée au propriétaire du compte",
    nav_landing:"Pages de destination",landing_title:"🎯 Pages de destination",create_landing:"Créer une page",
    landing_name:"Nom du produit",landing_desc:"Description du produit",landing_images:"Images du produit (jusqu'à 4)",
    landing_cta_type:"Le bouton redirige vers",landing_cta_store:"🛍️ Ma boutique en ligne",landing_cta_whatsapp:"💬 WhatsApp",
    landing_whatsapp_number:"Numéro WhatsApp (format international)",landing_generate_btn:"Générer avec l'IA",
    landing_next_btn:"Suivant : questions",landing_questions_intro:"Répondez à ces questions pour une page plus professionnelle (facultatif)",back:"Retour",
    landing_generating:"Génération en cours...",landing_created:"Page créée avec succès",
    landing_empty:"Aucune page de destination — créez la première",landing_published:"Publiée",landing_unpublished:"Suspendue",
    landing_views:"vues",landing_preview:"Aperçu",landing_copy_link:"Copier le lien",
    landing_delete_confirm:"Supprimer cette page ?",landing_post_ig:"Publier sur Instagram",
    landing_post_ig_confirm:"Publier cette page sur votre compte Instagram connecté ?",
    locked_landing:"Pages de destination non disponibles",upgrade_landing:"Passez au plan Starter ou supérieur"
  },
  AR:{
    nav_dashboard:"الرئيسية",nav_orders:"الطلبات",nav_products:"المنتجات",
    nav_customers:"العملاء",nav_cities:"المدن",nav_store:"المتجر",nav_bot:"بوت الذكاء",
    nav_plans:"الاشتراكات",nav_settings:"الإعدادات",nav_discounts:"أكواد الخصم", nav_tracking:"التتبع الإعلاني",nav_shipping:"شركات الشحن", nav_assistant:"المساعد الإداري",nav_support:"الدعم الفني", logout:"تسجيل الخروج",
    total_orders:"إجمالي الطلبات",confirmed:"المؤكدة",refused:"المرفوضة",
    delivered:"تم التسليم",total_profit:"إجمالي الأرباح",top_products:"أفضل المنتجات",
    low_stock:"مخزون منخفض",add_order:"إضافة طلب",add_product:"إضافة منتج",
    add_city:"إضافة مدينة",client:"العميل",phone:"الهاتف",product:"المنتج",
    qty:"الكمية",city:"المدينة",total:"المجموع",profit:"الربح",source:"المصدر",
    status:"الحالة",date:"التاريخ",sent:"تاريخ الإرسال",delivered_date:"تاريخ التسليم",
    address:"العنوان",notes:"ملاحظات",add:"إضافة",cancel:"إلغاء",save:"حفظ",
    settings:"إعدادات",bot_settings:"إعدادات البوت",bot_logs:"سجلات البوت",
    instructions:"التعليمات",store_settings:"إعدادات المتجر",
    locked_store:"المتجر غير متاح",upgrade_store:"قم بالترقية إلى Starter أو أعلى",
    locked_bot:"بوت الذكاء غير متاح",upgrade_bot:"قم بالترقية إلى Pro أو Full",
    see_plans:"عرض الاشتراكات",account:"الحساب",username:"اسم المستخدم",
    plan:"الباقة",connect_fb:"ربط فيسبوك",disconnect:"قطع الاتصال",
    plan_contact:"للتغيير إلى باقة مختلفة، تواصل مع المسؤول.",
    loginTagline:"منصة إدارة المبيعات",user:"اسم المستخدم",pass:"كلمة المرور",login_btn:"تسجيل الدخول",
    delivery_type:"نوع التوصيل",home_delivery:"🏠 للمنزل",desk_delivery:"🏢 مكتب الاستلام",
    home_section:"🏠 توصيل للمنزل",desk_section:"🏢 توصيل لمكتب الاستلام (Stop Desk)",
    ship_cost:"تكلفة التوصيل",ship_cust:"رسوم الزبون",return_fee_shared:"رسوم الإرجاع (مشتركة)",
    delivery_col:"التوصيل",home_short:"🏠 منزل",desk_short:"🏢 مكتب",select_delivery:"— اختر نوع التوصيل —",
    nav_integrations:"ربط المتجر",locked_integrations:"ربط المتجر غير متاح",upgrade_integrations:"قم بالترقية إلى Pro أو Full",
    woo_desc:"اربط متجر WooCommerce تبعك، وOrderFlow يسحب طلباته تلقائياً.",
    woo_store_url:"رابط المتجر (https://...)",woo_consumer_key:"Consumer Key",woo_consumer_secret:"Consumer Secret",
    woo_connect_btn:"ربط المتجر",woo_connected:"متصل",woo_sync_now:"🔄 مزامنة الآن",
    woo_disconnect:"فك الربط",woo_last_sync:"آخر مزامنة",
    bot_coming_soon_title:"🚀 البوت قريباً",bot_coming_soon_desc:"نعمل دروك على تفعيل المساعد الذكي رسمياً (بانتظار موافقة Meta على إنستغرام). راح نخبرك أول واحد وقت يطلع!",
    bill_monthly:"شهري",bill_yearly:"سنوي (وفّر شهرين)",
    pf_orders:"إدارة الطلبات",pf_dashboard:"لوحة تحكم",pf_store:"متجر عام",pf_bot:"بوت AI",
    pf_all_starter:"كل ميزات Starter",pf_woo:"ربط WooCommerce",pf_all_pro:"كل ميزات Pro",pf_vip:"دعم VIP",
    pf_bot_soon:"بوت AI (قريباً)",pf_all_inclusive:"كل ما سبق + WooCommerce",
    pf_bot_soon_cap:"بوت AI (سقف 3,000 رسالة/شهر)",pf_order_cap:"سقف 300 طلب/شهر",
    pf_lifetime:"دفعة واحدة — مدى الحياة",
    home_cost_th:"🏠 منزل (تكلفة)",home_cust_th:"🏠 منزل (زبون)",
    desk_cost_th:"🏢 مكتب (تكلفة)",desk_cust_th:"🏢 مكتب (زبون)",
    nav_messages:"المحادثات",locked_messages:"المحادثات غير متاحة",
    upgrade_messages:"قم بالترقية إلى Pro أو Full",no_conversations:"لا توجد محادثات",
    select_conversation:"اختر محادثة لعرضها",type_message:"اكتب رسالة...",
    chart_status:"📊 توزيع حالة الطلبات",chart_trend:"📈 الأرباح خلال 7 أيام",chart_topproducts:"🏆 أفضل المنتجات مبيعاً",
    nav_team:"الفريق",add_member:"إضافة عضو",member_username:"اسم المستخدم",member_name:"الاسم",
    member_password:"كلمة السر",permissions:"الصلاحيات",active:"نشط",inactive:"معطّل",
    locked_team:"ميزة الفريق غير متاحة",upgrade_team:"قم بالترقية إلى Starter أو أعلى",
    edit:"تعديل",delete:"حذف",confirm_delete_member:"حذف هذا العضو من الفريق؟",
    team_count_of:"عضو من أصل",leave_blank_password:"اتركها فارغة إذا ما بغيتيش تبدّلها",
    owner_only_feature:"هذه الميزة متاحة فقط لصاحب الحساب",
    nav_landing:"صفحات الهبوط",landing_title:"🎯 صفحات الهبوط",create_landing:"صمم صفحة جديدة",
    landing_name:"اسم المنتج",landing_desc:"وصف المنتج",landing_images:"صور المنتج (حتى 4)",
    landing_cta_type:"زر الطلب يوجّه إلى",landing_cta_store:"🛍️ متجري الإلكتروني",landing_cta_whatsapp:"💬 واتساب",
    landing_whatsapp_number:"رقم واتساب (بصيغة دولية)",landing_generate_btn:"صمم بالذكاء الاصطناعي",
    landing_next_btn:"التالي: أسئلة احترافية",landing_questions_intro:"جاوب على هاذ الأسئلة باش الذكاء الاصطناعي يصمملك صفحة احترافية أكثر (اختياري)",back:"رجوع",
    landing_generating:"جاري التصميم...",landing_created:"تم إنشاء الصفحة بنجاح",
    landing_empty:"لا توجد صفحات هبوط بعد — صمم أول صفحة الآن",landing_published:"منشورة",landing_unpublished:"موقوفة",
    landing_views:"مشاهدة",landing_preview:"معاينة",landing_copy_link:"نسخ الرابط",
    landing_delete_confirm:"حذف هذه الصفحة؟",landing_post_ig:"نشر على إنستغرام",
    landing_post_ig_confirm:"نشر هذه الصفحة على حساب إنستغرام المرتبط؟",
    locked_landing:"صفحات الهبوط غير متاحة",upgrade_landing:"قم بالترقية إلى Starter أو أعلى"
  },
  EN:{
    nav_dashboard:"Dashboard",nav_orders:"Orders",nav_products:"Products",
    nav_customers:"Customers",nav_cities:"Cities",nav_store:"Store",nav_bot:"AI Bot",
    nav_plans:"Plans",nav_settings:"Settings",nav_discounts:"Discount Codes", nav_tracking:"Ad Tracking",nav_shipping:"Shipping Companies", nav_assistant:"Admin Assistant",nav_support:"Technical Support", logout:"Logout",
    total_orders:"Total Orders",confirmed:"Confirmed",refused:"Refused",
    delivered:"Delivered",total_profit:"Total Profit",top_products:"Top Products",
    low_stock:"Low Stock",add_order:"Add Order",add_product:"Add Product",
    add_city:"Add City",client:"Customer",phone:"Phone",product:"Product",
    qty:"Qty",city:"City",total:"Total",profit:"Profit",source:"Source",
    status:"Status",date:"Date",sent:"Sent Date",delivered_date:"Delivered Date",
    address:"Address",notes:"Notes",add:"Add",cancel:"Cancel",save:"Save",
    settings:"Settings",bot_settings:"Bot Settings",bot_logs:"Bot Logs",
    instructions:"Instructions",store_settings:"Store Settings",
    locked_store:"Store Unavailable",upgrade_store:"Upgrade to Starter or higher",
    locked_bot:"AI Bot Unavailable",upgrade_bot:"Upgrade to Pro or Full",
    see_plans:"View Plans",account:"Account",username:"Username",
    plan:"Plan",connect_fb:"Connect Facebook",disconnect:"Disconnect",
    plan_contact:"To change your plan, contact the administrator.",
    loginTagline:"Sales Management Platform",user:"Username",pass:"Password",login_btn:"Login",
    delivery_type:"Delivery Type",home_delivery:"🏠 Home",desk_delivery:"🏢 Pickup Office (Stop Desk)",
    home_section:"🏠 Home Delivery",desk_section:"🏢 Pickup Office (Stop Desk)",
    ship_cost:"Shipping Cost",ship_cust:"Customer Fee",return_fee_shared:"Return Fee (shared)",
    delivery_col:"Delivery",home_short:"🏠 Home",desk_short:"🏢 Office",select_delivery:"— Select delivery type —",
    nav_integrations:"Integrations",locked_integrations:"Integration Unavailable",upgrade_integrations:"Upgrade to Pro or Full",
    woo_desc:"Connect your WooCommerce store, OrderFlow will import its orders automatically.",
    woo_store_url:"Store URL (https://...)",woo_consumer_key:"Consumer Key",woo_consumer_secret:"Consumer Secret",
    woo_connect_btn:"Connect Store",woo_connected:"Connected",woo_sync_now:"🔄 Sync Now",
    woo_disconnect:"Disconnect",woo_last_sync:"Last sync",
    bot_coming_soon_title:"🚀 Coming Soon",bot_coming_soon_desc:"We're officially activating the AI assistant soon (pending Meta's approval for Instagram). You'll be the first to know when it launches!",
    bill_monthly:"Monthly",bill_yearly:"Yearly (save 2 months)",
    pf_orders:"Order management",pf_dashboard:"Dashboard",pf_store:"Online store",pf_bot:"AI Bot",
    pf_all_starter:"All Starter features",pf_woo:"WooCommerce connection",pf_all_pro:"All Pro features",pf_vip:"VIP support",
    pf_bot_soon:"AI Bot (coming soon)",pf_all_inclusive:"All included + WooCommerce",
    pf_bot_soon_cap:"AI Bot (3,000 msgs/month cap)",pf_order_cap:"300 orders/month cap",
    pf_lifetime:"One-time payment — lifetime",
    home_cost_th:"🏠 Home (cost)",home_cust_th:"🏠 Home (customer)",
    desk_cost_th:"🏢 Office (cost)",desk_cust_th:"🏢 Office (customer)",
    nav_messages:"Messages",locked_messages:"Messages Unavailable",
    upgrade_messages:"Upgrade to Pro or Full",no_conversations:"No conversations",
    select_conversation:"Select a conversation",type_message:"Type a message...",
    chart_status:"📊 Order status breakdown",chart_trend:"📈 Profit (last 7 days)",chart_topproducts:"🏆 Best-selling products",
    nav_team:"Team",add_member:"Add Member",member_username:"Username",member_name:"Name",
    member_password:"Password",permissions:"Permissions",active:"Active",inactive:"Inactive",
    locked_team:"Team feature unavailable",upgrade_team:"Upgrade to Starter or higher",
    edit:"Edit",delete:"Delete",confirm_delete_member:"Delete this team member?",
    team_count_of:"member(s) of",leave_blank_password:"Leave blank to keep unchanged",
    owner_only_feature:"This feature is available to the account owner only",
    nav_landing:"Landing Pages",landing_title:"🎯 Landing Pages",create_landing:"Create New Page",
    landing_name:"Product Name",landing_desc:"Product Description",landing_images:"Product Images (up to 4)",
    landing_cta_type:"Order button links to",landing_cta_store:"🛍️ My Online Store",landing_cta_whatsapp:"💬 WhatsApp",
    landing_whatsapp_number:"WhatsApp number (international format)",landing_generate_btn:"Generate with AI",
    landing_next_btn:"Next: questions",landing_questions_intro:"Answer these questions for a more professional page (optional)",back:"Back",
    landing_generating:"Generating...",landing_created:"Page created successfully",
    landing_empty:"No landing pages yet — create your first one",landing_published:"Published",landing_unpublished:"Unpublished",
    landing_views:"views",landing_preview:"Preview",landing_copy_link:"Copy Link",
    landing_delete_confirm:"Delete this page?",landing_post_ig:"Post to Instagram",
    landing_post_ig_confirm:"Post this page to your connected Instagram account?",
    locked_landing:"Landing Pages Unavailable",upgrade_landing:"Upgrade to Starter or higher"
  }
};

function t(k){ return (I18N[currentLang]||I18N.FR)[k] || k; }
// ── حماية من XSS: escape إجباري لأي نص جاي من مصدر غير موثوق (زبون/عميل)
// قبل إدراجه فـ innerHTML. بيانات الطلبات (name/phone/city/product) تجي من
// /api/addOrder العام بلا مصادقة — أي زبون يقدر يدخل <script> أو onerror=...
// كاسم، ووقت التاجر يفتح لوحة الطلبات يتنفذ الكود فمتصفحه ويسرق التوكن.
function esc(s){
  return String(s === undefined || s === null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}
// ما تدمجش قيم نصية داخل onclick="f('...')" — المتصفح يفك &#39; قبل ما يشغّل JS.
// حط القيمة فـ data-* (مهرّبة بـ esc) واقراها بـ this.dataset.
function applyLang(lang){
  currentLang = lang;
  localStorage.setItem("of_lang", lang);
  var isAr = lang === "AR";
  document.documentElement.setAttribute("lang", lang.toLowerCase());
  document.documentElement.setAttribute("dir", isAr ? "rtl" : "ltr");
  document.querySelectorAll("[data-i18n]").forEach(function(el){
    var k = el.getAttribute("data-i18n");
    el.textContent = t(k);
  });
  document.querySelectorAll(".lang-btn").forEach(function(b){
    b.classList.remove("active");
    if(b.textContent.trim() === lang) b.classList.add("active");
  });
  var lu = document.getElementById("loginTagline");
  if(lu) lu.textContent = t("loginTagline");
  var lblU = document.getElementById("lblUser");
  if(lblU) lblU.textContent = t("user");
  var lblP = document.getElementById("lblPass");
  if(lblP) lblP.textContent = t("pass");
  var lb = document.getElementById("loginBtnTxt");
  if(lb) lb.textContent = t("login_btn");
  document.querySelectorAll(".currency").forEach(function(el){
    el.textContent = lang==="AR"?"دج":lang==="EN"?"$":"€";
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(function(el){
    var k = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(k));
  });
  var activeSec = document.querySelector(".section.active");
  if(activeSec && activeSec.id==="sec_dashboard" && currentUser) loadDashboard();
  if(activeSec && activeSec.id==="sec_team" && currentUser) renderTeamTable(TEAM_MEMBERS);
}

function setLang(l){ applyLang(l); }

// =========================================================
// TOAST
// =========================================================
function toast(msg, type){
  var w = document.getElementById("toastWrap");
  var d = document.createElement("div");
  d.className = "toast "+(type||"ok");
  d.textContent = msg;
  w.appendChild(d);
  setTimeout(function(){ d.remove(); }, 3500);
}

// =========================================================
// LOGIN
// =========================================================
async function doLogin(){
  var u = document.getElementById("loginUser").value.trim();
  var p = document.getElementById("loginPass").value.trim();
  if(!u||!p){ showLoginErr("Remplissez tous les champs"); return; }
  var btn = document.getElementById("loginBtn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try{
    var r = await apiPost("/login", {username:u, password:p}, false);
    if(r.status==="ok"){
      authToken   = r.data.token || null;
      if(authToken) localStorage.setItem("of_token", authToken);
      enterDashboard(r.data, u);
    } else {
      showLoginErr(r.message||"Identifiants incorrects");
    }
  }catch(e){ showLoginErr("Erreur serveur"); }
  finally{ btn.disabled=false; btn.innerHTML='<span id="loginBtnTxt">'+t("login_btn")+'</span>'; }
}

// يفتح اللوحة لمستخدم معروف — بعد تسجيل الدخول، أو بعد reload عبر restoreSession()
function enterDashboard(user, displayName){
  currentUser = user;
  currentRole = user.role || "owner";
  var name = displayName || user.Username || "";
  document.getElementById("loginPage").style.display="none";
  document.getElementById("sideUser").textContent = name;
  document.getElementById("topUser").textContent = name;
  document.getElementById("s_user").value = name;
  document.getElementById("s_uid").value = currentUser.User_ID||"";
  loadUserPlan();
  loadDashboard();
  applyLang(currentLang);
  startOrdersPolling();
}

// بعد reload: of_token محفوظ فـ localStorage — نتحقق منو عبر /api/me ونعاود نفتح اللوحة.
// نخرّجو (ونمسحو التوكن) غير إلا السيرفر رفضو (401/403). خطأ شبكة أو 5xx: نخلّيو التوكن
// ونبيّنو صفحة الدخول، والـ reload الجاي يعاود يجرّب.
async function restoreSession(){
  if(SHOP_UID || !authToken) return;
  var lp = document.getElementById("loginPage");
  lp.style.display = "none";
  try{
    var r = await fetch(API_URL+"/me", {headers: {"Authorization":"Bearer "+authToken}});
    if(r.status===401 || r.status===403){ logout(); return; }
    var d = await r.json();
    if(r.ok && d.status==="ok" && d.data){ enterDashboard(d.data); return; }
  }catch(e){}
  lp.style.display = "flex";
}

function showLoginErr(m){
  var e = document.getElementById("loginErr");
  e.textContent = m; e.style.display="block";
}

document.getElementById("loginPass").addEventListener("keydown", function(e){
  if(e.key==="Enter") doLogin();
});

function logout(){
  currentUser = null;
  authToken   = null;
  currentRole = "owner";
  TEAM_MEMBERS = [];
  // طلبات الحساب السابق ما يبقاوش فالذاكرة (الـ polling يدمج، ما يعوّضش)
  allOrders = []; ORDERS_BY_ID = {}; ORDERS_CURSOR = null; ORDERS_OLDEST = null; ORDERS_HAS_MORE = false;
  CONV_MAP = {}; CONV_CURSOR = null; CONV_OLDEST = null; CONV_HAS_MORE = false;
  CONV_MSGS = []; CONV_MSGS_SENDER = null; CONV_LAST_KEY = null; CONV_FIRST_KEY = null; CURRENT_CONV_SENDER = null;
  localStorage.removeItem("of_token");
  stopOrdersPolling();
  stopConvListPolling();
  stopConvPolling();
  document.getElementById("loginPage").style.display="flex";
  document.getElementById("loginUser").value="";
  document.getElementById("loginPass").value="";
  document.getElementById("loginErr").style.display="none";
}

// =========================================================
// API  (يرفق تلقائياً Authorization: Bearer <token> على كل طلب محمي)
// =========================================================
async function apiGet(path, params, authed){
  if(authed === undefined) authed = true;
  var url = API_URL + path;
  if(params){
    var q = new URLSearchParams(params);
    url += "?" + q.toString();
  }
  var headers = {};
  if(authed && authToken) headers["Authorization"] = "Bearer " + authToken;
  var r = await fetch(url, {headers: headers});
  return r.json();
}

async function apiPost(path, body, authed){
  if(authed === undefined) authed = true;
  var headers = {"Content-Type":"application/json"};
  if(authed && authToken) headers["Authorization"] = "Bearer " + authToken;
  var r = await fetch(API_URL + path, {
    method:"POST", headers: headers,
    body: JSON.stringify(body)
  });
  return r.json();
}

function uid(){ return currentUser ? (currentUser.User_ID||currentUser.user_id||"") : ""; }
function uname(){ return currentUser ? (currentUser.Username||currentUser.username||"") : ""; }

// =========================================================
// SECTIONS
// =========================================================
function showSection(s){
  if(s==="plans" && USER_SOURCE==="fiverr"){ s = "store"; }
  if(s==="team" && currentRole!=="owner"){ toast("⛔ "+t("owner_only_feature"),"err"); return; }
  document.querySelectorAll(".section").forEach(function(el){ el.classList.remove("active"); });
  document.querySelectorAll(".nav-item").forEach(function(el){ el.classList.remove("active"); });
  var sec = document.getElementById("sec_"+s);
  if(sec) sec.classList.add("active");
  document.querySelectorAll(".nav-item").forEach(function(el){
    if(el.getAttribute("onclick") && el.getAttribute("onclick").includes("'"+s+"'")){
      el.classList.add("active");
    }
  });
  var titles = {
    dashboard:t("nav_dashboard"),orders:t("nav_orders"),products:t("nav_products"),
    customers:t("nav_customers"),cities:t("nav_cities"),store:t("nav_store"),
    bot:t("nav_bot"),messages:t("nav_messages"),integrations:t("nav_integrations"),
    team:t("nav_team"),plans:t("nav_plans"),settings:t("nav_settings"),landing:t("nav_landing")
  };
  document.getElementById("pageTitle").textContent = titles[s]||s;

  if(s==="dashboard") loadDashboard();
  else if(s==="orders") loadOrders();
  else if(s==="products") loadProducts();
  else if(s==="customers") loadCustomers();
  else if(s==="cities") loadCities();
  else if(s==="store") loadStore();
  else if(s==="landing") loadLanding();
  else if(s==="bot") loadBot();
  else if(s==="messages") loadMessagesSection();
  else if(s==="integrations") loadIntegrations();
  else if(s==="team") loadTeam();
  else if(s==="plans") highlightCurrentPlan();
  else if(s==="settings") loadSettings();
  if(s!=="messages"){ stopConvListPolling(); stopConvPolling(); }

  if(window.innerWidth <= 768){
    document.getElementById("sidebar").classList.remove("open");
  }
}

function toggleSidebar(){
  document.getElementById("sidebar").classList.toggle("open");
}

window.addEventListener("resize", function(){
  var mb = document.getElementById("menuToggle");
  if(mb) mb.style.display = window.innerWidth<=768?"block":"none";
});
window.dispatchEvent(new Event("resize"));

// =========================================================
// PLAN
// =========================================================
async function loadUserPlan(){
  try{
    var r = await apiGet("/getUserPlan", {});
    if(r.status==="ok"){
      currentPlan = r.data.plan;
      merchantCurrency = r.data.currency || "DZD";
      BOT_LAUNCHED = !!r.data.botLaunched;
      PLAN_USAGE = r.data.usage || {};
      USER_SOURCE = r.data.source || "local";
      LIFETIME_SLOTS_LEFT = r.data.lifetimeSlotsLeft;
      if(r.data.role) currentRole = r.data.role;
      TEAM_COUNT = r.data.teamCount || 0;
      var navPlansEl = document.getElementById("navPlans");
      if(navPlansEl) navPlansEl.style.display = (USER_SOURCE==="fiverr") ? "none" : "flex";
      var navTeamEl = document.getElementById("navTeam");
      if(navTeamEl) navTeamEl.style.display = (currentRole==="owner" && planHas("team")) ? "flex" : "none";
      renderCurrencyButtons();
      var pd = document.getElementById("planDisplay");
      if(pd) pd.innerHTML = 'Plan: <span class="plan-badge plan-'+currentPlan+'">'+currentPlan.toUpperCase()+'</span>';
      document.getElementById("s_plan").value = currentPlan;
    }
  }catch(e){}
}

function planHas(feature){
  var features = {
    free:       {bot:false,store:false,landing:false,integrations:false,team:false},
    starter:    {bot:false,store:true, landing:true, integrations:false,team:true},
    pro:        {bot:true, store:true, landing:true, integrations:true, team:true},
    enterprise: {bot:true, store:true, landing:true, integrations:true, team:true},
    full:       {bot:true, store:true, landing:true, integrations:true, team:true},
    lifetime:   {bot:true, store:true, landing:true, integrations:true, team:true}
  };
  return (features[currentPlan]||features.free)[feature]||false;
}

function setBillingCycle(cycle){
  var isYearly = cycle==="yearly";
  document.getElementById("billMonthlyBtn").classList.toggle("active", !isYearly);
  document.getElementById("billYearlyBtn").classList.toggle("active", isYearly);
  document.querySelectorAll(".price-m").forEach(function(el){ el.style.display = isYearly?"none":"inline"; });
  document.querySelectorAll(".price-y").forEach(function(el){ el.style.display = isYearly?"inline":"none"; });
  document.querySelectorAll(".unit-m").forEach(function(el){ el.style.display = isYearly?"none":"inline"; });
  document.querySelectorAll(".unit-y").forEach(function(el){ el.style.display = isYearly?"inline":"none"; });
}

function highlightCurrentPlan(){
  ["free","starter","pro","enterprise","full","lifetime"].forEach(function(p){
    var el = document.getElementById("plan_"+p);
    if(el) el.classList.toggle("current", p===currentPlan);
  });
  var badge = document.getElementById("lifetimeSlotsBadge");
  if(badge){
    if(LIFETIME_SLOTS_LEFT!==null && LIFETIME_SLOTS_LEFT!==undefined){
      badge.style.display = "inline-block";
      badge.textContent = "🔥 "+LIFETIME_SLOTS_LEFT+" من 50 متبقي فقط";
    } else {
      badge.style.display = "none";
    }
  }
  var box = document.getElementById("usageBox");
  var keys = Object.keys(PLAN_USAGE||{});
  if(!keys.length){ box.style.display="none"; return; }
  box.style.display = "block";
  var labels = {orders:"الطلبات هذا الشهر", botMsgs:"رسائل البوت هذا الشهر"};
  box.innerHTML = keys.map(function(k){
    var u = PLAN_USAGE[k];
    var pct = Math.min(100, Math.round((u.used/u.cap)*100));
    var color = pct>=90?"var(--red)":pct>=70?"var(--yellow)":"var(--green)";
    return '<div class="table-wrap" style="padding:16px;margin-bottom:10px">'+
      '<div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px">'+
        '<span>'+(labels[k]||k)+'</span><strong>'+u.used+' / '+u.cap+'</strong>'+
      '</div>'+
      '<div style="background:var(--card2);border-radius:6px;height:8px;overflow:hidden">'+
        '<div style="width:'+pct+'%;height:100%;background:'+color+'"></div>'+
      '</div></div>';
  }).join("");
}

// =========================================================
// DASHBOARD
// =========================================================
var chartStatusInstance   = null;
var chartTrendInstance    = null;
var chartProductsInstance = null;

function chartTextColor(){ return DARK_MODE ? "#8899bb" : "#64748b"; }
function chartGridColor(){ return DARK_MODE ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.07)"; }

async function loadDashboard(){
  try{
    var r = await apiGet("/getDashboard", {});
    if(r.status!=="ok") return;
    var d = r.data;
    var cur = curSym();
    document.getElementById("d_total").textContent  = d.totalOrders||0;
    document.getElementById("d_conf").textContent   = (d.confirmed||0)+" ("+d.delivered+" "+t("delivered")+")";
    document.getElementById("d_ref").textContent    = d.refused||0;
    document.getElementById("d_profit").textContent = (d.totalProfit||0).toLocaleString()+" "+cur;

    var topTbl = document.getElementById("topProductsTbl");
    topTbl.innerHTML = (d.topProducts||[]).map(function(p){
      return "<tr><td>"+esc(p.name)+"</td><td><strong>"+esc(p.qty)+"</strong></td></tr>";
    }).join("") || '<tr><td colspan="2" class="empty-state">—</td></tr>';

    var lowTbl = document.getElementById("lowStockTbl");
    lowTbl.innerHTML = (d.lowStock||[]).map(function(p){
      var cl = p.rem<=0?"br":"bn";
      return "<tr><td>"+esc(p.name)+"</td><td>"+esc(p.rem)+"</td><td><span class='badge "+cl+"'>"+esc(p.stat)+"</span></td></tr>";
    }).join("") || '<tr><td colspan="3" class="empty-state">✅</td></tr>';

    renderStatusChart(d, cur);
    renderProductsChart(d);
    loadTrendChart(cur);
  }catch(e){ console.error(e); }
}

function renderStatusChart(d, cur){
  var canvas = document.getElementById("chartStatus");
  if(!canvas || typeof Chart==="undefined") return;
  var deliveredOnly = d.delivered||0;
  var confirmedOnly = Math.max(0, (d.confirmed||0) - deliveredOnly);
  var refusedOnly   = d.refused||0;
  var pendingOnly   = Math.max(0, (d.totalOrders||0) - confirmedOnly - deliveredOnly - refusedOnly);
  var labels = [t("confirmed"), t("delivered"), t("refused"), "Pending"];
  var data   = [confirmedOnly, deliveredOnly, refusedOnly, pendingOnly];

  if(chartStatusInstance) chartStatusInstance.destroy();
  chartStatusInstance = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: ["#3b82f6","#10b981","#ef4444","#f59e0b"],
        borderColor: "transparent",
        borderWidth: 2,
        hoverOffset: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: { position: "bottom", labels: { color: chartTextColor(), font:{size:11}, padding:12, usePointStyle:true, boxWidth:8 } },
        tooltip: { callbacks: { label: function(ctx){ return " "+ctx.label+": "+ctx.parsed; } } }
      }
    }
  });

  var cap = document.getElementById("chartStatusCaption");
  if(cap){
    cap.innerHTML = "<strong>"+(d.totalOrders||0)+"</strong> "+t("total_orders")+" — "+
      "<strong style='color:var(--green)'>"+(d.confirmRate||0)+"%</strong> "+t("confirmed")+" · "+
      "<strong style='color:var(--red)'>"+(d.refuseRate||0)+"%</strong> "+t("refused");
  }
}

function renderProductsChart(d){
  var canvas = document.getElementById("chartProducts");
  if(!canvas || typeof Chart==="undefined") return;
  var top = (d.topProducts||[]).slice(0,5);

  if(chartProductsInstance) chartProductsInstance.destroy();
  chartProductsInstance = new Chart(canvas, {
    type: "bar",
    data: {
      labels: top.map(function(p){ return p.name.length>14 ? p.name.substring(0,14)+"…" : p.name; }),
      datasets: [{
        label: t("sold"),
        data: top.map(function(p){ return p.qty; }),
        backgroundColor: "#2563eb",
        borderRadius: 6,
        maxBarThickness: 26
      }]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display:false }, tooltip:{ callbacks:{ label:function(ctx){ return " "+ctx.parsed.x+" "+t("sold"); } } } },
      scales: {
        x: { beginAtZero:true, ticks:{ color: chartTextColor(), precision:0 }, grid:{ color: chartGridColor() } },
        y: { ticks:{ color: chartTextColor(), font:{size:11} }, grid:{ display:false } }
      }
    }
  });

  var cap = document.getElementById("chartProductsCaption");
  if(cap){
    cap.textContent = top.length
      ? ("🥇 "+top[0].name+" — "+top[0].qty+" "+(t("sold")||"").toLowerCase())
      : "—";
  }
}

async function loadTrendChart(cur){
  var canvas = document.getElementById("chartTrend");
  if(!canvas || typeof Chart==="undefined") return;
  try{
    // غير طلبات آخر 8 أيام (المنحنى يبيّن 7) — بدل كل الطلبات
    var r = await apiGet("/getOrders", {createdAfter: Date.now() - 8*86400000});
    var orders = (r.status==="ok") ? (r.data||[]) : [];
    var days = [], map = {};
    for(var i=6;i>=0;i--){
      var dt = new Date(); dt.setDate(dt.getDate()-i);
      var key = dt.toISOString().slice(0,10);
      days.push(key); map[key] = 0;
    }
    orders.forEach(function(o){
      if(!o.date) return;
      var key = o.date.slice(0,10);
      if(map.hasOwnProperty(key) && (o.status==="Confirmed"||o.status==="Delivered"||o.status==="Refused")){
        map[key] += parseFloat(o.profit||0);
      }
    });
    var localeMap = {AR:"ar-DZ", EN:"en-US", FR:"fr-FR"};
    var labels = days.map(function(k){
      var dt = new Date(k+"T00:00:00");
      return dt.toLocaleDateString(localeMap[currentLang]||"fr-FR", {day:"2-digit", month:"2-digit"});
    });
    var values = days.map(function(k){ return Math.round(map[k]); });

    if(chartTrendInstance) chartTrendInstance.destroy();
    chartTrendInstance = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [{
          label: t("total_profit"),
          data: values,
          borderColor: "#10b981",
          backgroundColor: "rgba(16,185,129,.15)",
          fill: true, tension: .35, pointRadius: 3, pointBackgroundColor: "#10b981", borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display:false }, tooltip: { callbacks: { label:function(ctx){ return " "+ctx.parsed.y.toLocaleString()+" "+(cur||""); } } } },
        scales: {
          x: { ticks:{ color: chartTextColor(), font:{size:11} }, grid:{ display:false } },
          y: { ticks:{ color: chartTextColor() }, grid:{ color: chartGridColor() } }
        }
      }
    });

    var total7 = values.reduce(function(s,v){ return s+v; },0);
    var cap = document.getElementById("chartTrendCaption");
    if(cap) cap.innerHTML = (currentLang==="AR"?"إجمالي 7 أيام: ":currentLang==="EN"?"7-day total: ":"Total 7 jours: ")+
      "<strong style='color:"+(total7>=0?"var(--green)":"var(--red)")+"'>"+total7.toLocaleString()+" "+(cur||"")+"</strong>";
  }catch(e){ console.error(e); }
}

// =========================================================
// ORDERS
// =========================================================
// الطلبات المحمّلة: آخر 200، و"تحميل الأقدم" يزيد صفحات. الـ polling يجيب غير اللي تبدّل
// من بعد ORDERS_CURSOR (وقت السيرفر)، ويندمج بالـ id.
var ORDERS_BY_ID    = {};
var ORDERS_CURSOR   = null;
var ORDERS_OLDEST   = null;   // أقدم createdAt محمّل عبر الصفحات (ماشي عبر الـ polling)
var ORDERS_HAS_MORE = false;
var ORDERS_PAGE     = 200;

function _mergeOrders(list, fromPage){
  var changed = false;
  (list||[]).forEach(function(o){
    if(!o || !o.id) return;
    // طلب قديم بزاف (برا الصفحات المحمّلة) ما يدخلش من الـ polling، باش "تحميل الأقدم" يبقى صحيح
    if(!fromPage && !ORDERS_BY_ID[o.id] && ORDERS_HAS_MORE && (o.createdAt||0) < ORDERS_OLDEST) return;
    ORDERS_BY_ID[o.id] = o; changed = true;
  });
  allOrders = Object.keys(ORDERS_BY_ID).map(function(k){ return ORDERS_BY_ID[k]; })
    .sort(function(a,b){ return (b.createdAt||0)-(a.createdAt||0); });
  return changed;
}

function _applyOrdersPage(r){
  var created = (r.data||[]).map(function(o){ return o.createdAt||0; });
  if(created.length) ORDERS_OLDEST = Math.min.apply(null, created.concat(ORDERS_OLDEST===null?[]:[ORDERS_OLDEST]));
  ORDERS_HAS_MORE = !!r.hasMore;
  _mergeOrders(r.data, true);
  var more = document.getElementById("ordersMoreWrap");
  if(more) more.style.display = ORDERS_HAS_MORE ? "block" : "none";
}

async function loadOrders(){
  var tbl = document.getElementById("ordersTbl");
  tbl.innerHTML = '<tr><td colspan="15" class="empty-state"><span class="spinner"></span></td></tr>';
  try{
    var r = await apiGet("/getOrders", {limit: ORDERS_PAGE});
    if(r.status==="ok"){
      ORDERS_BY_ID = {}; ORDERS_OLDEST = null;
      ORDERS_CURSOR = r.cursor;
      _applyOrdersPage(r);
      filterOrders();
    } else { tbl.innerHTML='<tr><td colspan="15" class="empty-state">'+esc(r.message||"Erreur")+'</td></tr>'; }
  }catch(e){ tbl.innerHTML='<tr><td colspan="15" class="empty-state">Erreur</td></tr>'; }
}

async function loadOlderOrders(){
  if(!ORDERS_HAS_MORE || ORDERS_OLDEST===null) return;
  try{
    var r = await apiGet("/getOrders", {limit: ORDERS_PAGE, before: ORDERS_OLDEST});
    if(r.status==="ok"){ _applyOrdersPage(r); filterOrders(); }
    else toast("❌ "+(r.message||"Erreur"),"err");
  }catch(e){ toast("Erreur réseau","err"); }
}

// تبدّلات فقط من بعد آخر cursor. ما كاين حتى نداء كي يكون التبويب مخفي.
async function pollOrders(){
  if(!authToken || document.hidden) return;
  var activeSec = document.querySelector(".section.active");
  if(!activeSec || activeSec.id!=="sec_orders") return;
  if(ORDERS_CURSOR===null){ loadOrders(); return; }
  try{
    var r = await apiGet("/getOrders", {since: ORDERS_CURSOR});
    if(r.status!=="ok") return;
    if(r.reset){ loadOrders(); return; }
    ORDERS_CURSOR = r.cursor;
    if(r.data && r.data.length && _mergeOrders(r.data, false)) filterOrders();
  }catch(e){}
}

function renderOrders(orders){
  var tbl = document.getElementById("ordersTbl");
  if(!orders||!orders.length){
    tbl.innerHTML='<tr><td colspan="15"><div class="empty-state"><i class="bi bi-bag"></i>'+t("nav_orders")+'</div></td></tr>';
    return;
  }
  var cur = curSym();
  tbl.innerHTML = orders.map(function(o,i){
    var stCls = {Pending:"bp",Confirmed:"bc",Delivered:"bi",Refused:"br","No Answer":"bn"}[o.status]||"bp";
    var opts = ["Pending","Confirmed","Delivered","Refused","No Answer"].map(function(s){
      return '<option value="'+s+'"'+(o.status===s?" selected":"")+'>'+s+'</option>';
    }).join("");
    var safeId = esc(o.id);
    return '<tr>'+
      '<td>'+(i+1)+'</td>'+
      '<td style="font-size:11px">'+esc(o.date||"—")+'</td>'+
      '<td><strong>'+esc(o.name||"—")+'</strong></td>'+
      '<td><a href="tel:'+esc(o.phone||"")+'" style="color:var(--accent)">'+esc(o.phone||"—")+'</a></td>'+
      '<td>'+esc(o.product||"—")+'</td>'+
      '<td>'+esc(o.qty||1)+'</td>'+
      '<td>'+esc(o.city||"—")+'</td>'+
      '<td>'+
        '<span class="badge bn me-1">'+(o.deliveryType==="desk"?t("desk_short"):t("home_short"))+'</span>'+
        '<select class="status-sel" data-id="'+safeId+'" onchange="updateOrderDelivery(this.dataset.id,this.value)">'+
          '<option value="home"'+(o.deliveryType!=="desk"?" selected":"")+'>'+t("home_delivery")+'</option>'+
          '<option value="desk"'+(o.deliveryType==="desk"?" selected":"")+'>'+t("desk_delivery")+'</option>'+
        '</select>'+
      '</td>'+
      '<td><strong>'+esc(o.total||0)+' '+cur+'</strong></td>'+
      '<td style="color:'+(parseFloat(o.profit||0)>=0?"var(--green)":"var(--red)")+'">'+esc(o.profit||0)+' '+cur+'</td>'+
      '<td><span class="badge bn">'+esc(o.source||"manual")+'</span></td>'+
      '<td style="font-size:11px;color:var(--muted)">'+esc(o.date_sent||"—")+'</td>'+
      '<td style="font-size:11px;color:var(--muted)">'+esc(o.date_delivered||"—")+'</td>'+
          '<td>'+
        '<span class="badge '+stCls+' me-1">'+esc(o.status)+'</span>'+
        '<select class="status-sel" onchange="updateStatus(this.dataset.id,this.value)" data-id="'+safeId+'">'+opts+'</select>'+
      '</td>'+
      '<td><button class="btn-outline btn-sm" data-id="'+safeId+'" onclick="printOrderSlip(this.dataset.id)" title="طباعة بون دو كوموند"><i class="bi bi-printer"></i></button></td>'+
    '</tr>';
  }).join("");
}

function filterOrders(){
  var q   = (document.getElementById("orderSearch").value||"").toLowerCase();
  var st  = document.getElementById("statusFilter").value;
  var res = allOrders.filter(function(o){
    var match = !q || (o.name||"").toLowerCase().includes(q)
                   || (o.phone||"").includes(q)
                   || (o.product||"").toLowerCase().includes(q)
                   || (o.city||"").toLowerCase().includes(q);
    var stMatch = !st || o.status===st;
    return match && stMatch;
  });
  renderOrders(res);
}

async function updateStatus(orderId, newStatus){
  try{
    var r = await apiPost("/updateStatus", {orderId:orderId, status:newStatus});
    if(r.status==="ok"){
      toast("✅ Statut mis à jour: "+newStatus, "ok");
      var o = allOrders.find(function(x){ return x.id===orderId; });
      if(o){
        o.status = newStatus;
        var now = new Date().toLocaleString("fr-DZ");
        if(newStatus==="Confirmed" && !o.date_sent)   o.date_sent      = now;
        if(newStatus==="Delivered" && !o.date_delivered) o.date_delivered = now;
      }
      renderOrders(allOrders);
    } else { toast("❌ "+r.message, "err"); }
  }catch(e){ toast("Erreur réseau","err"); }
}

async function updateOrderDelivery(orderId, newType){
  try{
    var r = await apiPost("/updateOrderDelivery", {orderId:orderId, deliveryType:newType});
    if(r.status==="ok"){
      toast("✅ تم تحديث نوع التوصيل","ok");
      loadOrders(); // إعادة تحميل لضمان دقة الإجمالي والربح المُعاد حسابهما من السيرفر
    } else { toast("❌ "+r.message, "err"); }
  }catch(e){ toast("Erreur réseau","err"); }
}

async function addOrder(){
  var data = {
    name:    document.getElementById("o_name").value.trim(),
    phone:   document.getElementById("o_phone").value.trim(),
    product: document.getElementById("o_product").value,
    qty:     parseInt(document.getElementById("o_qty").value)||1,
    city:    document.getElementById("o_city").value,
    deliveryType: document.getElementById("o_delivery").value,
    address: document.getElementById("o_address").value.trim(),
    notes:   document.getElementById("o_notes").value.trim(),
  };
  if(!data.name||!data.phone||!data.product||!data.city){
    toast("Remplissez les champs obligatoires","err"); return;
  }
  if(!data.deliveryType){
    toast("اختر نوع التوصيل (منزل أو مكتب الاستلام)","err"); return;
  }
  var r = await apiPost("/addOrder", {userId:uid(), data:data}, false);
  if(r.status==="ok"){
    toast("✅ Commande ajoutée","ok");
    closeModal("addOrderModal");
    loadOrders();
  } else { toast("❌ "+r.message,"err"); }
}
// =========================================================
// طباعة بون دو كوموند + كود بار لكل طلب (يُسلَّم لشركة التوصيل)
// =========================================================
// =========================================================
// طباعة بون دو كوموند + كود بار لكل طلب (يُسلَّم لشركة التوصيل)
// ملاحظة: نبني الـ HTML بتجميع نص عادي (+) بلا backticks وبلا أي وسم
// <script> جوه النافذة المنبثقة — لأن أي وسم <script> أو backtick متداخل
// جوه template literal يقدر يكسر بارسينغ الصفحة الرئيسية بالكامل. نولّد
// الباركود هنا فالصفحة الرئيسية (JsBarcode محمّلة أصلاً فالـ head) ونحقن
// الـ SVG الجاهز كنص عادي داخل الصفحة المطبوعة.
// =========================================================
async function printOrderSlip(orderId){
  var o = allOrders.find(function(x){ return x.id===orderId; });
  if(!o){ toast("الطلب غير موجود","err"); return; }

  var storeName = "متجري";
  try{
    var sr = await apiGet("/getStoreSettings", {userId: uid()}, false);
    if(sr.status==="ok" && sr.data && sr.data.name) storeName = sr.data.name;
  }catch(e){}

  var cur = curSym();
  var deliveryLabel = o.deliveryType==="desk" ? "🏢 مكتب الاستلام (Stop Desk)" : "🏠 توصيل للمنزل";

  var barcodeSvgMarkup = "";
  try{
    var tmpSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    JsBarcode(tmpSvg, o.id, { format:"CODE128", width:2, height:55, displayValue:true, fontSize:13, margin:6 });
    barcodeSvgMarkup = tmpSvg.outerHTML;
  }catch(e){ barcodeSvgMarkup = ""; }

  var w = window.open("", "_blank", "width=420,height=600");
  if(!w){ toast("فعّل النوافذ المنبثقة (Popups) للطباعة","err"); return; }

  var html = "";
  html += "<!DOCTYPE html><html lang=\"ar\" dir=\"rtl\"><head><meta charset=\"UTF-8\"/>";
  html += "<title>بون كوموند — " + esc(o.id) + "</title>";
  html += "<style>";
  html += "*{box-sizing:border-box;margin:0;padding:0;font-family:Arial,'Segoe UI',sans-serif}";
  html += "body{padding:16px;color:#111}";
  html += ".slip{max-width:380px;margin:0 auto;border:2px solid #111;border-radius:6px;padding:14px}";
  html += ".head{text-align:center;border-bottom:2px dashed #111;padding-bottom:10px;margin-bottom:10px}";
  html += ".head h2{font-size:18px}";
  html += ".head small{color:#555;font-size:11px}";
  html += ".barcode-wrap{text-align:center;margin:10px 0}";
  html += ".row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px dotted #ccc;font-size:13px}";
  html += ".row span:first-child{color:#555}";
  html += ".row span:last-child{font-weight:700}";
  html += ".cod{background:#111;color:#fff;text-align:center;padding:10px;border-radius:6px;margin-top:10px;font-size:16px;font-weight:800}";
  html += ".foot{text-align:center;margin-top:10px;font-size:11px;color:#777}";
  html += "@media print{ .no-print{display:none} }";
  html += ".no-print{text-align:center;margin-top:14px}";
  html += ".no-print button{padding:8px 20px;font-size:14px;cursor:pointer}";
  html += "</style></head><body>";
  html += "<div class=\"slip\">";
  html += "<div class=\"head\"><h2>" + esc(storeName) + "</h2><small>بون كوموند / Bon de Commande</small></div>";
  html += "<div class=\"barcode-wrap\">" + barcodeSvgMarkup + "</div>";
  html += "<div class=\"row\"><span>رقم الطلب</span><span>" + esc(o.id) + "</span></div>";
  html += "<div class=\"row\"><span>التاريخ</span><span>" + esc(o.date||"—") + "</span></div>";
  html += "<div class=\"row\"><span>الزبون</span><span>" + esc(o.name||"—") + "</span></div>";
  html += "<div class=\"row\"><span>الهاتف</span><span>" + esc(o.phone||"—") + "</span></div>";
  html += "<div class=\"row\"><span>الولاية</span><span>" + esc(o.city||"—") + "</span></div>";
  html += "<div class=\"row\"><span>العنوان</span><span>" + esc(o.address||"—") + "</span></div>";
  html += "<div class=\"row\"><span>نوع التوصيل</span><span>" + esc(deliveryLabel) + "</span></div>";
  html += "<div class=\"row\"><span>المنتج</span><span>" + esc(o.product||"—") + "</span></div>";
  html += "<div class=\"row\"><span>الكمية</span><span>" + esc(o.qty||1) + "</span></div>";
  html += "<div class=\"cod\">المبلغ للتحصيل: " + esc(o.total||0) + " " + esc(cur) + "</div>";
  html += "<div class=\"foot\">Propulsé par OrderFlow</div>";
  html += "</div>";
  html += "<div class=\"no-print\"><button onclick=\"window.print()\">🖨️ طباعة</button></div>";
  html += "</body></html>";

  w.document.open();
  w.document.write(html);
  w.document.close();
}

// =========================================================
// PRODUCTS
// =========================================================
async function loadProducts(){
  var tbl = document.getElementById("productsTbl");
  tbl.innerHTML = '<tr><td colspan="11" class="empty-state"><span class="spinner"></span></td></tr>';
  try{
    var r = await apiGet("/getProducts", {});
    if(r.status==="ok"){
      var products = r.data||[];
      var cur = curSym();
      tbl.innerHTML = products.map(function(p){
        var stCls = {InStock:"bc","In Stock":"bc","Low Stock":"bn",LowStock:"bn","Out of Stock":"br",OutOfStock:"br"}[p.stat||""]||"bp";
        return '<tr>'+
          '<td><strong>'+esc(p.name||"—")+'</strong></td>'+
          '<td>'+esc(p.category||"—")+'</td>'+
          '<td>'+esc(p.size||"—")+'</td>'+
          '<td>'+esc(p.colors||"—")+'</td>'+
          '<td>'+esc(p.cost||0)+' '+cur+'</td>'+
          '<td><strong>'+esc(p.sell||0)+' '+cur+'</strong></td>'+
          '<td>'+esc(p.init||0)+'</td>'+
          '<td>'+esc(p.sold||0)+'</td>'+
          '<td>'+esc(p.available||0)+'</td>'+
          '<td><span class="badge '+stCls+'">'+esc(p.stat||"?")+'</span></td>'+
          '<td><button class="btn-danger" data-name="'+esc(p.name)+'" onclick="deleteProduct(this.dataset.name)"><i class="bi bi-trash"></i></button></td>'+
        '</tr>';
      }).join("") || '<tr><td colspan="11"><div class="empty-state"><i class="bi bi-box-seam"></i></div></td></tr>';
    }
  }catch(e){ console.error(e); }
}

async function addProduct(){
  var data = {
    name:p_name.value.trim(), category:p_cat.value.trim(), size:p_size.value.trim(),
    colors:p_colors.value.trim(), cost:parseFloat(p_cost.value)||0,
    sell:parseFloat(p_sell.value)||0, init:parseInt(p_init.value)||0,
    image:currentProductImages[0]||"", images:currentProductImages.slice(),
    description:p_desc.value.trim()
  };
  if(!data.name){ toast("Entrez un nom de produit","err"); return; }
  var r = await apiPost("/addProduct", {data:data});
  if(r.status==="ok"){
    toast("✅ Produit ajouté","ok");
    currentProductImages = [];
    renderProductImageThumbs();
    closeModal("addProductModal");
    loadProducts();
  } else { toast("❌ "+r.message,"err"); }
}

async function deleteProduct(name){
  if(!confirm("Supprimer "+name+" ?")) return;
  var r = await apiPost("/deleteProduct", {data:{name:name}});
  if(r.status==="ok"){ toast("✅ Supprimé","ok"); loadProducts(); }
  else { toast("❌ "+r.message,"err"); }
}

// =========================================================
// CUSTOMERS
// =========================================================
async function loadCustomers(){
  try{
    var r = await apiGet("/getCustomers", {});
    if(r.status==="ok"){
      allCustomers = r.data||[];
      renderCustomers(allCustomers);
    }
  }catch(e){ console.error(e); }
}

function renderCustomers(list){
  var tbl = document.getElementById("customersTbl");
  tbl.innerHTML = list.map(function(c){
    var typeCls = {Good:"bc",Bad:"br",Neutral:"bn"}[c.type]||"bp";
    return '<tr>'+
      '<td><strong>'+esc(c.name||"—")+'</strong></td>'+
      '<td>'+esc(c.phone||"—")+'</td>'+
      '<td>'+esc(c.city||"—")+'</td>'+
      '<td>'+esc(c.totalOrders||0)+'</td>'+
      '<td style="color:var(--green)">'+esc(c.stats&&c.stats.confirmed||0)+'</td>'+
      '<td style="color:var(--blue)">'+esc(c.stats&&c.stats.delivered||0)+'</td>'+
      '<td style="color:var(--red)">'+esc(c.stats&&c.stats.refused||0)+'</td>'+
      '<td><span class="badge '+typeCls+'">'+esc(c.type||"?")+'</span></td>'+
    '</tr>';
  }).join("") || '<tr><td colspan="8"><div class="empty-state"><i class="bi bi-people"></i></div></td></tr>';
}

function filterCustomers(){
  var q = (document.getElementById("custSearch").value||"").toLowerCase();
  renderCustomers(allCustomers.filter(function(c){
    return !q || (c.name||"").toLowerCase().includes(q) || (c.phone||"").includes(q);
  }));
}

// =========================================================
// CITIES
// =========================================================
async function loadCities(){
  try{
    var r = await apiGet("/getCities", {});
    if(r.status==="ok"){
      var cur = curSym();
      var tbl = document.getElementById("citiesTbl");
      tbl.innerHTML = (r.data||[]).map(function(c){
        return '<tr>'+
          '<td><strong>'+esc(c.name||"—")+'</strong></td>'+
          '<td>'+esc(c.costShip||0)+' '+cur+'</td>'+
          '<td>'+esc(c.custShip||0)+' '+cur+'</td>'+
          '<td>'+esc(c.deskCost||0)+' '+cur+'</td>'+
          '<td>'+esc(c.deskCust||0)+' '+cur+'</td>'+
          '<td>'+esc(c.returnFee||0)+' '+cur+'</td>'+
          '<td><button class="btn-danger" data-name="'+esc(c.name)+'" onclick="deleteCity(this.dataset.name)"><i class="bi bi-trash"></i></button></td>'+
        '</tr>';
      }).join("") || '<tr><td colspan="7"><div class="empty-state"><i class="bi bi-geo-alt"></i></div></td></tr>';

      var citySel = document.getElementById("o_city");
      if(citySel){
        citySel.innerHTML = (r.data||[]).map(function(c){
          return '<option value="'+esc(c.name)+'">'+esc(c.name)+'</option>';
        }).join("");
      }
    }
  }catch(e){ console.error(e); }
}

async function deleteCity(name){
  if(!confirm("حذف "+name+" نهائياً؟ (هذا يزيل التسعيرة الخاصة بها فقط، الطلبات القديمة تبقى محفوظة)")) return;
  try{
    var r = await apiPost("/deleteCity", {name:name});
    if(r.status==="ok"){ toast("✅ تم حذف الولاية","ok"); loadCities(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("خطأ فالاتصال","err"); }
}

async function addCity(){
  var data = {
    name:    c_name.value.trim(),
    costShip:parseFloat(c_cost.value)||0,
    custShip:parseFloat(c_cust.value)||0,
    deskCost:parseFloat(c_deskcost.value)||0,
    deskCust:parseFloat(c_deskcust.value)||0,
    returnFee:parseFloat(c_ret.value)||0,
  };
  if(!data.name){ toast("Entrez un nom de ville","err"); return; }
  var r = await apiPost("/addCity", {data:data});
  if(r.status==="ok"){ toast("✅ Ville ajoutée","ok"); closeModal("addCityModal"); loadCities(); }
  else { toast("❌ "+r.message,"err"); }
}

async function prefillOrderSelects(){
  try{
    var pr = await apiGet("/getProducts", {});
    var prodSel = document.getElementById("o_product");
    if(prodSel && pr.status==="ok"){
      prodSel.innerHTML = (pr.data||[]).map(function(p){
        return '<option value="'+esc(p.name)+'">'+esc(p.name)+'</option>';
      }).join("");
    }
    var cr = await apiGet("/getCities", {});
    var citySel = document.getElementById("o_city");
    if(citySel && cr.status==="ok"){
      citySel.innerHTML = (cr.data||[]).map(function(c){
        return '<option value="'+esc(c.name)+'">'+esc(c.name)+'</option>';
      }).join("");
    }
  }catch(e){}
}

// =========================================================
// STORE
// =========================================================
async function loadStore(){
  var hasStore = planHas("store");
  document.getElementById("storeLocked").style.display  = hasStore ? "none"  : "block";
  document.getElementById("storeContent").style.display = hasStore ? "block" : "none";
  var linkEl = document.getElementById("storeLinkInput");
  if(linkEl && currentUser && currentUser.User_ID){
    linkEl.value = window.location.origin + "/?store=" + currentUser.User_ID;
  }
  if(!hasStore) return;
  try{
    var sr = await apiGet("/getStoreSettings", {userId: uid()}, false);
    if(sr.status==="ok"){
      var s = sr.data||{};
      document.getElementById("storeTitle").innerHTML = (s.logoImage ? '<img src="'+esc(s.logoImage)+'" style="width:22px;height:22px;object-fit:contain;vertical-align:middle;border-radius:4px"/> ' : esc(s.logo||"🛒")+" ")+esc(s.name||"Ma Boutique");
      document.getElementById("ss_name").value    = s.name||"";
      document.getElementById("ss_tagline").value = s.tagline||"";
      document.getElementById("ss_logo").value    = s.logo||"🛒";
      document.getElementById("ss_currency").value = s.currency||"DZD";
      currentStoreLogoImage = s.logoImage||"";
      renderStoreLogoPreview();
    }
    var pr = await apiGet("/getStoreProducts", {userId: uid()}, false);
    var grid = document.getElementById("storeGrid");
    if(pr.status==="ok"){
      var cur = curSym();
      grid.innerHTML = (pr.data||[]).filter(function(p){ return p.visible!=="no"; }).map(function(p){
        var stCls = {"In Stock":"bc","Low Stock":"bn","Out of Stock":"br"}[p.stat]||"bp";
        return '<div class="store-card">'+
          '<div style="position:relative">'+
            (p.image
              ? '<img src="'+esc(p.image)+'" alt="'+esc(p.name)+'" style="width:100%;height:160px;object-fit:cover" onerror="this.style.display=\'none\'"/>'
              : '<div style="height:160px;display:flex;align-items:center;justify-content:center;background:var(--card2);font-size:40px">📦</div>')+
            '<label style="position:absolute;bottom:8px;right:8px;background:var(--accent);color:#fff;padding:5px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-weight:600;display:inline-flex;align-items:center;gap:4px">'+
              '📸 Changer'+
              '<input type="file" accept="image/*" style="display:none" data-name="'+esc(p.name)+'" onchange="uploadStoreProductImage(this,this.dataset.name)"/>'+
            '</label>'+
          '</div>'+
          '<div class="store-card-body">'+
            '<div class="store-card-title">'+esc(p.name)+'</div>'+
            '<div style="font-size:11px;color:var(--muted);margin:3px 0">'+esc(p.category||"")+'</div>'+
            '<div class="store-card-price">'+esc(p.sell||0)+' '+cur+'</div>'+
            '<div style="margin-top:8px"><span class="store-badge badge '+stCls+'">'+esc(p.stat)+'</span></div>'+
          '</div></div>';
      }).join("") || '<div class="empty-state"><i class="bi bi-shop"></i></div>';
    }
  }catch(e){ console.error(e); }
}

var currentStoreLogoImage = "";

function renderStoreLogoPreview(){
  var box = document.getElementById("ss_logo_preview");
  if(!box) return;
  box.innerHTML = currentStoreLogoImage
    ? '<div class="thumb-item"><img src="'+esc(currentStoreLogoImage)+'"/><button class="rm" onclick="removeStoreLogoImage()">✕</button></div>'
    : '';
}

function removeStoreLogoImage(){
  currentStoreLogoImage = "";
  renderStoreLogoPreview();
}

async function uploadStoreLogoImage(input){
  var file = input.files[0];
  if(!file) return;
  var box = document.getElementById("ss_logo_preview");
  box.innerHTML = '<span class="spinner"></span>';
  try{
    currentStoreLogoImage = await _uploadImageFile(file);
    renderStoreLogoPreview();
  }catch(e){
    toast("❌ فشل رفع صورة اللوغو","err");
    renderStoreLogoPreview();
  }
}

async function saveStoreSettings(){
  var r = await apiPost("/updateStoreSettings", {data:{
    name:     document.getElementById("ss_name").value.trim(),
    tagline:  document.getElementById("ss_tagline").value.trim(),
    logo:     document.getElementById("ss_logo").value.trim(),
    logoImage:currentStoreLogoImage,
    currency: document.getElementById("ss_currency").value,
  }});
  if(r.status==="ok"){
    merchantCurrency = document.getElementById("ss_currency").value;
    renderCurrencyButtons();
    toast("✅ Sauvegardé","ok"); closeModal("storeSettingsModal"); loadStore();
  }
  else { toast("❌ "+r.message,"err"); }
}

// =========================================================
// LANDING PAGES — صفحات هبوط مصممة بالذكاء الاصطناعي
// =========================================================
var currentLandingImages = [];
var LANDING_PAGES = [];
var currentLandingQuestions = [];

function renderLandingImageThumbs(){
  var wrap = document.getElementById("lp_img_thumbs");
  if(!wrap) return;
  wrap.innerHTML = currentLandingImages.map(function(url, i){
    return '<div class="thumb-item"><img src="'+url+'"/><button class="rm" onclick="removeLandingImage('+i+')">✕</button></div>';
  }).join("");
}

function removeLandingImage(i){
  currentLandingImages.splice(i,1);
  renderLandingImageThumbs();
}

async function addLandingImages(input){
  var files = Array.prototype.slice.call(input.files||[]).slice(0, 4 - currentLandingImages.length);
  if(!files.length) return;
  var statusEl = document.getElementById("lp_img_upload_status");
  statusEl.textContent = "⏳ جاري الرفع..."; statusEl.style.color = "var(--yellow)";
  try{
    for(var i=0;i<files.length;i++){
      var url = await _uploadImageFile(files[i]);
      currentLandingImages.push(url);
    }
    renderLandingImageThumbs();
    statusEl.textContent = "✅ تم الرفع بنجاح"; statusEl.style.color = "var(--green)";
  }catch(e){
    statusEl.textContent = "❌ فشل الرفع"; statusEl.style.color = "var(--red)";
    console.error("Upload error:", e);
  }
}

function toggleLandingCtaFields(){
  var sel = document.getElementById("lp_cta_type");
  var wrap = document.getElementById("lp_wa_wrap");
  if(!sel || !wrap) return;
  wrap.style.display = sel.value==="whatsapp" ? "block" : "none";
}

// ── خطوة 1→2: نجمع الأسئلة الذكية من السيرفر قبل التصميم النهائي ──
function lp_backToStep1(){
  document.getElementById("lp_step1").style.display = "block";
  document.getElementById("lp_step2").style.display = "none";
}

async function lp_goToQuestions(){
  var name  = document.getElementById("lp_name").value.trim();
  var desc  = document.getElementById("lp_desc").value.trim();
  var ctaType = document.getElementById("lp_cta_type").value;
  var waNumber = document.getElementById("lp_wa_number").value.trim();
  if(!name || !desc){ toast("أدخل اسم المنتج ووصفه","err"); return; }
  if(!currentLandingImages.length){ toast("أضف صورة واحدة على الأقل","err"); return; }
  if(ctaType==="whatsapp" && !waNumber){ toast("أدخل رقم واتساب","err"); return; }

  var btn = document.getElementById("lp_next_btn");
  var orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try{
    var r = await apiPost("/landing/questions", {name:name, description:desc});
    if(r.status==="ok"){
      currentLandingQuestions = r.data.questions || [];
      renderLandingQuestions();
      document.getElementById("lp_step1").style.display = "none";
      document.getElementById("lp_step2").style.display = "block";
    } else {
      toast("❌ "+r.message,"err");
    }
  }catch(e){ toast("Erreur réseau","err"); }
  finally{ btn.disabled=false; btn.innerHTML=orig; }
}

function renderLandingQuestions(){
  var box = document.getElementById("lp_questions");
  box.innerHTML = currentLandingQuestions.map(function(q){
    var safeId = String(q.id).replace(/[^a-zA-Z0-9_-]/g,"");
    return '<div class="form-group"><label>'+esc(q.question)+'</label>'+
      '<textarea class="form-control lp-answer" data-qid="'+esc(safeId)+'" rows="2"></textarea></div>';
  }).join("");
}

function _collectLandingAnswers(){
  var out = {};
  document.querySelectorAll(".lp-answer").forEach(function(el){
    var v = el.value.trim();
    if(v) out[el.dataset.qid] = v;
  });
  return out;
}

async function generateLandingPage(){
  var name  = document.getElementById("lp_name").value.trim();
  var desc  = document.getElementById("lp_desc").value.trim();
  var ctaType = document.getElementById("lp_cta_type").value;
  var waNumber = document.getElementById("lp_wa_number").value.trim();
  var answers = _collectLandingAnswers();
  if(!name || !desc){ toast("أدخل اسم المنتج ووصفه","err"); return; }
  if(!currentLandingImages.length){ toast("أضف صورة واحدة على الأقل","err"); return; }
  if(ctaType==="whatsapp" && !waNumber){ toast("أدخل رقم واتساب","err"); return; }
  var btn = document.getElementById("lp_generate_btn");
  var origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> '+t("landing_generating");
  try{
    var r = await apiPost("/landing/generate", {
      name:name, description:desc, images:currentLandingImages,
      ctaType:ctaType, whatsappNumber:waNumber, answers:answers
    });
    if(r.status==="ok"){
      toast("✅ "+t("landing_created"),"ok");
      closeModal("createLandingModal");
      document.getElementById("lp_name").value = "";
      document.getElementById("lp_desc").value = "";
      document.getElementById("lp_wa_number").value = "";
      currentLandingImages = [];
      currentLandingQuestions = [];
      renderLandingImageThumbs();
      lp_backToStep1();
      loadLanding();
    } else {
      toast("❌ "+r.message,"err");
    }
  }catch(e){ toast("Erreur réseau","err"); }
  finally{ btn.disabled=false; btn.innerHTML=origHtml; }
}

async function loadLanding(){
  var hasLanding = planHas("landing");
  document.getElementById("landingLocked").style.display  = hasLanding ? "none"  : "block";
  document.getElementById("landingContent").style.display = hasLanding ? "block" : "none";
  if(!hasLanding) return;
  var grid = document.getElementById("landingGrid");
  grid.innerHTML = '<div style="text-align:center;padding:40px;grid-column:1/-1"><span class="spinner" style="width:28px;height:28px;border-width:3px"></span></div>';
  try{
    var r = await apiGet("/landing/list", {});
    if(r.status==="ok"){
      LANDING_PAGES = r.data||[];
      renderLandingList(LANDING_PAGES);
    } else {
      grid.innerHTML = '';
      toast("❌ "+r.message,"err");
    }
  }catch(e){ grid.innerHTML=''; }
}

function renderLandingList(list){
  var grid  = document.getElementById("landingGrid");
  var empty = document.getElementById("landingEmpty");
  if(!list || !list.length){ grid.innerHTML=""; empty.style.display="block"; return; }
  empty.style.display = "none";
  grid.innerHTML = list.map(function(p){
    var img = (p.images&&p.images[0]) ? '<img src="'+esc(p.images[0])+'" style="width:100%;height:160px;object-fit:cover" onerror="this.style.display=\'none\'"/>'
                                       : '<div style="height:160px;display:flex;align-items:center;justify-content:center;background:var(--card2);font-size:40px">🎯</div>';
    var pubBadge = p.published ? '<span class="badge bc">'+t("landing_published")+'</span>' : '<span class="badge bp">'+t("landing_unpublished")+'</span>';
    var igBadge  = p.instagramPostId ? '<span class="badge bi" style="margin-right:4px">📷 IG</span>' : '';
    return '<div class="store-card">'+
      img+
      '<div class="store-card-body">'+
        '<div class="store-card-title">'+esc(p.name)+'</div>'+
        '<div style="font-size:11px;color:var(--muted);margin:4px 0">'+esc(p.created_at||"")+' · 👁️ '+esc(p.views||0)+' '+t("landing_views")+'</div>'+
        '<div style="margin-bottom:8px">'+pubBadge+' '+igBadge+'</div>'+
        '<div style="display:flex;gap:6px;flex-wrap:wrap" data-id="'+esc(p.id)+'" data-url="'+esc(p.publicUrl)+'">'+
          '<button class="btn-outline btn-sm" onclick="window.open(this.closest(\'div[data-url]\').dataset.url,\'_blank\')"><i class="bi bi-eye"></i> '+t("landing_preview")+'</button>'+
          '<button class="btn-outline btn-sm" onclick="copyLandingLink(this.closest(\'div[data-url]\').dataset.url)"><i class="bi bi-clipboard"></i> '+t("landing_copy_link")+'</button>'+
          '<button class="btn-success" onclick="toggleLandingPublish(this.closest(\'div[data-id]\').dataset.id)">'+(p.published?'⏸️':'▶️')+'</button>'+
          '<button class="btn-primary btn-sm" onclick="postLandingToInstagram(this.closest(\'div[data-id]\').dataset.id)"><i class="bi bi-instagram"></i> '+t("landing_post_ig")+'</button>'+
          '<button class="btn-danger" onclick="deleteLandingPage(this.closest(\'div[data-id]\').dataset.id)"><i class="bi bi-trash"></i></button>'+
        '</div>'+
      '</div></div>';
  }).join("");
}

function copyLandingLink(url){
  navigator.clipboard?.writeText(url);
  toast("✅ تم نسخ الرابط","ok");
}

async function toggleLandingPublish(pageId){
  try{
    var r = await apiPost("/landing/togglePublish", {pageId:pageId});
    if(r.status==="ok"){ toast("✅","ok"); loadLanding(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("Erreur réseau","err"); }
}

async function deleteLandingPage(pageId){
  if(!confirm(t("landing_delete_confirm"))) return;
  try{
    var r = await apiPost("/landing/delete", {pageId:pageId});
    if(r.status==="ok"){ toast("✅ "+t("delete"),"ok"); loadLanding(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("Erreur réseau","err"); }
}

async function postLandingToInstagram(pageId){
  if(!confirm(t("landing_post_ig_confirm"))) return;
  try{
    var r = await apiPost("/landing/postToInstagram", {pageId:pageId});
    if(r.status==="ok"){ toast("✅ تم النشر على إنستغرام","ok"); loadLanding(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("Erreur réseau","err"); }
}

// =========================================================
// BOT
// =========================================================
async function loadBot(){
  var hasBot = planHas("bot");
  document.getElementById("botComingSoon").style.display = (hasBot && !BOT_LAUNCHED) ? "block" : "none";
  document.getElementById("botLocked").style.display  = (!hasBot) ? "block" : "none";
  document.getElementById("botContent").style.display = (hasBot && BOT_LAUNCHED) ? "block" : "none";
  if(!hasBot || !BOT_LAUNCHED) return;
  checkFbStatus();

  try{
    var r = await apiGet("/getBotSettings", {});
    if(r.status==="ok"){
      var u = r.data||{};
      document.getElementById("b_gemini").value  = u.Gemini_api_key||"";
      document.getElementById("b_inst").value    = u.AI_instructions||"";
      document.getElementById("b_watoken").value = u.whtsapp_token||"";
      document.getElementById("b_phone_id").value= u.phone_number_id||"";
      document.getElementById("b_fbtoken").value = u.fb_access_token||"";
      document.getElementById("b_fbpage").value  = u.page_id_FB||"";
      document.getElementById("b_igtoken").value = u.instgram_access_token||"";
      document.getElementById("b_igpage").value  = u.Page_ID_instgram||"";
    }
  }catch(e){}
  loadBotLogs();
}

// =========================================================
// MESSAGES / CONVERSATIONS — إرسال واستقبال رسائل العملاء عبر Meta API
// =========================================================
var CURRENT_CONV_SENDER   = null;
var CURRENT_CONV_PLATFORM = null;
var _convPollTimer     = null;
var _convListPollTimer = null;

function loadMessagesSection(){
  var hasBot = planHas("bot");
  document.getElementById("messagesComingSoon").style.display = (hasBot && !BOT_LAUNCHED) ? "block" : "none";
  document.getElementById("messagesLocked").style.display     = (!hasBot) ? "block" : "none";
  document.getElementById("messagesContent").style.display    = (hasBot && BOT_LAUNCHED) ? "flex" : "none";
  if(!hasBot || !BOT_LAUNCHED){ stopConvListPolling(); stopConvPolling(); return; }
  loadConversations();
  startConvListPolling();
}

// القائمة: آخر 50 محادثة، "تحميل الأقدم"، والـ polling يجيب غير اللي تحرّكو من بعد CONV_CURSOR
var CONV_MAP = {}, CONV_CURSOR = null, CONV_OLDEST = null, CONV_HAS_MORE = false;

function _convOldest(list){
  var ts = (list||[]).map(function(c){ return c.lastTimestamp||0; });
  if(!ts.length) return;
  CONV_OLDEST = Math.min.apply(null, ts.concat(CONV_OLDEST===null?[]:[CONV_OLDEST]));
}

function _renderConvMap(){
  var list = Object.keys(CONV_MAP).map(function(k){ return CONV_MAP[k]; })
    .sort(function(a,b){ return (b.lastTimestamp||0)-(a.lastTimestamp||0); });
  renderConversationsList(list);
}

async function loadConversations(){
  try{
    var r = await apiGet("/getConversations", CONV_CURSOR===null ? {} : {since: CONV_CURSOR});
    if(r.status!=="ok") return;
    if(r.reset){ CONV_CURSOR = null; CONV_MAP = {}; CONV_OLDEST = null; return loadConversations(); }
    var first = CONV_CURSOR===null;
    if(first){ CONV_MAP = {}; CONV_OLDEST = null; CONV_HAS_MORE = !!r.hasMore; _convOldest(r.data); }
    (r.data||[]).forEach(function(c){ CONV_MAP[c.senderId] = c; });
    CONV_CURSOR = r.cursor;
    if(first || (r.data||[]).length) _renderConvMap();
  }catch(e){ console.error(e); }
}

async function loadOlderConversations(){
  if(!CONV_HAS_MORE || CONV_OLDEST===null) return;
  try{
    var r = await apiGet("/getConversations", {before: CONV_OLDEST});
    if(r.status!=="ok") return;
    CONV_HAS_MORE = !!r.hasMore;
    _convOldest(r.data);
    (r.data||[]).forEach(function(c){ if(!CONV_MAP[c.senderId]) CONV_MAP[c.senderId] = c; });
    _renderConvMap();
  }catch(e){ console.error(e); }
}

function renderConversationsList(list){
  var el = document.getElementById("convList");
  if(!list.length){
    el.innerHTML = '<div class="empty-state"><i class="bi bi-chat-dots"></i>'+t("no_conversations")+'</div>';
    return;
  }
  el.innerHTML = list.map(function(c){
    var icon = c.platform==="wa" ? "📱" : c.platform==="ig" ? "📷" : "📘";
    var active = (c.senderId===CURRENT_CONV_SENDER) ? " active" : "";
    var dirIcon = c.lastDirection==="out" ? "↩️ " : "";
    var timeTxt = c.lastTimestamp ? new Date(c.lastTimestamp*1000).toLocaleString("fr-DZ",{hour:"2-digit",minute:"2-digit",day:"2-digit",month:"2-digit"}) : "";
    return '<div class="conv-item'+active+'" data-sid="'+esc(c.senderId)+'" data-platform="'+esc(c.platform)+'" data-name="'+esc(c.name||"")+'"'+
      ' onclick="openConversation(this.dataset.sid,this.dataset.platform,this.dataset.name)">'+
      '<div class="conv-avatar">'+icon+'</div>'+
      '<div class="conv-info">'+
        '<div class="conv-name">'+esc(c.name||c.senderId)+'</div>'+
        '<div class="conv-last">'+dirIcon+esc((c.lastMessage||"").substring(0,40))+'</div>'+
      '</div>'+
      '<div class="conv-time">'+esc(timeTxt)+'</div>'+
    '</div>';
  }).join("") + (CONV_HAS_MORE
    ? '<div style="text-align:center;padding:10px"><button class="btn-outline btn-sm" onclick="loadOlderConversations()">⬇️ المزيد / Plus</button></div>'
    : '');
}
function openConversation(senderId, platform, name){
  CURRENT_CONV_SENDER   = senderId;
  CURRENT_CONV_PLATFORM = platform;
  document.getElementById("convEmptyState").style.display = "none";
  document.getElementById("convChatPanel").style.display  = "flex";
  document.getElementById("convChatName").textContent = name || senderId;
  var icon = platform==="wa" ? "📱 WhatsApp" : platform==="ig" ? "📷 Instagram" : "📘 Facebook";
  document.getElementById("convChatPlatform").textContent = icon;
  CONV_MSGS = []; CONV_MSGS_SENDER = null; CONV_LAST_KEY = null; CONV_FIRST_KEY = null;
  loadConversationMessages(senderId);
  startConvPolling();
  loadConversations();
  if(window.innerWidth<=768){
    document.getElementById("convListWrap").classList.add("hide-mobile");
    document.getElementById("convRightWrap").classList.add("show-mobile");
  }
}

function backToConvList(){
  document.getElementById("convListWrap").classList.remove("hide-mobile");
  document.getElementById("convRightWrap").classList.remove("show-mobile");
}

// الرسائل: آخر 100، "رسائل أقدم"، والـ polling يجيب غير اللي من بعد CONV_LAST_KEY (مفتاح push)
var CONV_MSGS = [], CONV_MSGS_SENDER = null, CONV_LAST_KEY = null, CONV_FIRST_KEY = null, CONV_MSGS_HAS_MORE = false;

function _setMsgKeys(){
  CONV_FIRST_KEY = CONV_MSGS.length ? CONV_MSGS[0].id : null;
  CONV_LAST_KEY  = CONV_MSGS.length ? CONV_MSGS[CONV_MSGS.length-1].id : null;
}

async function loadConversationMessages(senderId, quiet){
  var box = document.getElementById("convMessages");
  if(!quiet) box.innerHTML = '<div style="text-align:center;padding:30px"><span class="spinner"></span></div>';
  try{
    var r = await apiGet("/getConversationMessages", {senderId: senderId});
    if(senderId!==CURRENT_CONV_SENDER) return;
    if(r.status==="ok"){
      CONV_MSGS = r.data||[]; CONV_MSGS_SENDER = senderId; CONV_MSGS_HAS_MORE = !!r.hasMore;
      _setMsgKeys();
      renderConversationMessages(CONV_MSGS);
    }
    else if(!quiet) box.innerHTML = '<div class="empty-state">'+esc(r.message||"Erreur")+'</div>';
  }catch(e){ if(!quiet) box.innerHTML = '<div class="empty-state">Erreur</div>'; }
}

async function pollConversationMessages(){
  var sender = CURRENT_CONV_SENDER;
  if(!sender) return;
  if(CONV_MSGS_SENDER!==sender || CONV_LAST_KEY===null){ loadConversationMessages(sender, true); return; }
  try{
    var r = await apiGet("/getConversationMessages", {senderId: sender, after: CONV_LAST_KEY});
    if(r.status!=="ok" || sender!==CURRENT_CONV_SENDER || !(r.data||[]).length) return;
    var seen = {}; CONV_MSGS.forEach(function(m){ seen[m.id] = 1; });
    CONV_MSGS = CONV_MSGS.concat(r.data.filter(function(m){ return !seen[m.id]; }));
    _setMsgKeys();
    renderConversationMessages(CONV_MSGS);
  }catch(e){}
}

async function loadOlderMessages(){
  var sender = CURRENT_CONV_SENDER;
  if(!sender || !CONV_MSGS_HAS_MORE || CONV_FIRST_KEY===null) return;
  try{
    var r = await apiGet("/getConversationMessages", {senderId: sender, before: CONV_FIRST_KEY});
    if(r.status!=="ok" || sender!==CURRENT_CONV_SENDER) return;
    CONV_MSGS = (r.data||[]).concat(CONV_MSGS); CONV_MSGS_HAS_MORE = !!r.hasMore;
    _setMsgKeys();
    renderConversationMessages(CONV_MSGS, true);
  }catch(e){}
}

function renderConversationMessages(items, keepScroll){
  var box = document.getElementById("convMessages");
  if(!items.length){ box.innerHTML='<div class="empty-state"><i class="bi bi-chat"></i></div>'; return; }
  var prevHeight = box.scrollHeight, prevTop = box.scrollTop;
  box.innerHTML = (CONV_MSGS_HAS_MORE
    ? '<div style="text-align:center;padding:6px"><button class="btn-outline btn-sm" onclick="loadOlderMessages()">⬆️ رسائل أقدم / Plus</button></div>'
    : '') + items.map(function(m){
    var cls = m.direction==="out" ? "msg-out" : "msg-in";
    var viaBadge = m.via==="manual" ? " 👤" : m.via==="bot" ? " 🤖" : "";
    var safeText = esc(m.text||"");
    return '<div class="msg-bubble-wrap '+cls+'"><div class="msg-bubble">'+safeText+'<div class="msg-meta">'+esc(m.date||"")+viaBadge+'</div></div></div>';
  }).join("");
  box.scrollTop = keepScroll ? (box.scrollHeight - prevHeight + prevTop) : box.scrollHeight;
}

async function sendCustomerMessage(){
  var input = document.getElementById("convInput");
  var text  = input.value.trim();
  if(!text || !CURRENT_CONV_SENDER) return;
  var btn = document.getElementById("convSendBtn");
  btn.disabled = true;
  try{
    var r = await apiPost("/sendMessage", {senderId: CURRENT_CONV_SENDER, text: text});
    if(r.status==="ok"){
      input.value = "";
      pollConversationMessages();
      loadConversations();
    } else { toast("❌ "+r.message,"err"); }
  }catch(e){ toast("Erreur réseau","err"); }
  finally{ btn.disabled = false; }
}

function startConvListPolling(){
  stopConvListPolling();
  _convListPollTimer = setInterval(function(){
    if(document.hidden) return;
    var activeSec = document.querySelector(".section.active");
    if(!activeSec || activeSec.id!=="sec_messages") return;
    loadConversations();
  }, 10000);
}
function stopConvListPolling(){
  if(_convListPollTimer){ clearInterval(_convListPollTimer); _convListPollTimer=null; }
}

function startConvPolling(){
  stopConvPolling();
  _convPollTimer = setInterval(function(){
    if(document.hidden) return;
    var activeSec = document.querySelector(".section.active");
    if(!activeSec || activeSec.id!=="sec_messages" || !CURRENT_CONV_SENDER) return;
    pollConversationMessages();
  }, 6000);
}
// رجوع للتبويب: تحديث فوري للمحادثات المفتوحة
document.addEventListener("visibilitychange", function(){
  if(document.hidden) return;
  var activeSec = document.querySelector(".section.active");
  if(!activeSec || activeSec.id!=="sec_messages") return;
  if(_convListPollTimer) loadConversations();
  if(_convPollTimer && CURRENT_CONV_SENDER) pollConversationMessages();
});
function stopConvPolling(){
  if(_convPollTimer){ clearInterval(_convPollTimer); _convPollTimer=null; }
}

document.addEventListener("DOMContentLoaded", function(){
  var ci = document.getElementById("convInput");
  if(ci) ci.addEventListener("keydown", function(e){
    if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendCustomerMessage(); }
  });
});

// =========================================================
// INTEGRATIONS — WooCommerce
// =========================================================
async function loadIntegrations(){
  var has = planHas("integrations");
  document.getElementById("integrationsLocked").style.display = has ? "none"  : "block";
  document.getElementById("integrationsContent").style.display = has ? "block" : "none";
  if(!has) return;
  try{
    var r = await apiGet("/woo/status", {});
    if(r.status==="ok" && r.data.connected){
      document.getElementById("wooDisconnected").style.display = "none";
      document.getElementById("wooConnected").style.display = "block";
      document.getElementById("wooStoreUrlDisplay").textContent = r.data.storeUrl;
      document.getElementById("wooLastSyncDisplay").textContent =
        (t("woo_last_sync")||"آخر مزامنة")+": "+(r.data.lastSync || "—");
    } else {
      document.getElementById("wooDisconnected").style.display = "block";
      document.getElementById("wooConnected").style.display = "none";
    }
  }catch(e){}
}

async function connectWoo(){
  var url    = document.getElementById("woo_url").value.trim();
  var key    = document.getElementById("woo_key").value.trim();
  var secret = document.getElementById("woo_secret").value.trim();
  var msgEl  = document.getElementById("wooConnectMsg");
  if(!url||!key||!secret){ msgEl.style.color="var(--red)"; msgEl.textContent="عبّي كل الحقول"; return; }
  var btn = document.getElementById("wooConnectBtn");
  btn.disabled = true; msgEl.style.color="var(--yellow)"; msgEl.textContent="⏳ جاري التحقق من الربط...";
  try{
    var r = await apiPost("/woo/connect", {storeUrl:url, consumerKey:key, consumerSecret:secret});
    if(r.status==="ok"){
      toast("✅ تم ربط المتجر بنجاح","ok");
      loadIntegrations();
    } else {
      msgEl.style.color="var(--red)"; msgEl.textContent="❌ "+r.message;
    }
  }catch(e){ msgEl.style.color="var(--red)"; msgEl.textContent="خطأ فالاتصال"; }
  finally{ btn.disabled = false; }
}

async function syncWoo(){
  var btn = document.getElementById("wooSyncBtn");
  var msgEl = document.getElementById("wooSyncMsg");
  btn.disabled = true; msgEl.style.color="var(--yellow)"; msgEl.textContent="⏳ جاري المزامنة...";
  try{
    var r = await apiPost("/woo/sync", {});
    if(r.status==="ok"){
      msgEl.style.color="var(--green)";
      msgEl.textContent="✅ تم استيراد "+r.data.imported+" طلب جديد (من "+r.data.checked+" تم فحصها)";
      toast("✅ المزامنة تمت بنجاح","ok");
      loadIntegrations();
    } else {
      msgEl.style.color="var(--red)"; msgEl.textContent="❌ "+r.message;
    }
  }catch(e){ msgEl.style.color="var(--red)"; msgEl.textContent="خطأ فالاتصال"; }
  finally{ btn.disabled = false; }
}

async function disconnectWoo(){
  if(!confirm("فك ربط متجر WooCommerce؟")) return;
  try{
    var r = await apiPost("/woo/disconnect", {});
    if(r.status==="ok"){ toast("✅ تم فك الربط","ok"); loadIntegrations(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("خطأ فالاتصال","err"); }
}

// =========================================================
// TEAM — إدارة أعضاء الفريق (owner فقط)
// =========================================================
function _teamPermLabel(key){
  var map = {
    orders:"nav_orders", products:"nav_products", customers:"nav_customers",
    cities:"nav_cities", store:"nav_store", bot:"nav_bot",
    messages:"nav_messages", integrations:"nav_integrations", landing:"nav_landing"
  };
  return t(map[key]||key);
}

async function loadTeam(){
  var hasTeam = planHas("team") && currentRole==="owner";
  document.getElementById("teamLocked").style.display  = hasTeam ? "none"  : "block";
  document.getElementById("teamContent").style.display = hasTeam ? "block" : "none";
  if(!hasTeam) return;
  var tbl = document.getElementById("teamTbl");
  tbl.innerHTML = '<tr><td colspan="5" class="empty-state"><span class="spinner"></span></td></tr>';
  try{
    var r = await apiGet("/team/listMembers", {});
    if(r.status==="ok"){
      TEAM_MEMBERS = r.data||[];
      renderTeamTable(TEAM_MEMBERS);
      var lbl = document.getElementById("teamCountLabel");
      if(lbl) lbl.textContent = TEAM_MEMBERS.length+" / "+TEAM_MAX+" "+t("team_count_of");
      var addBtn = document.getElementById("addMemberBtn");
      if(addBtn) addBtn.disabled = TEAM_MEMBERS.length >= TEAM_MAX;
    } else {
      tbl.innerHTML = '<tr><td colspan="5" class="empty-state">'+(r.message||"Erreur")+'</td></tr>';
    }
  }catch(e){ tbl.innerHTML = '<tr><td colspan="5" class="empty-state">Erreur</td></tr>'; }
}

function renderTeamTable(list){
  var tbl = document.getElementById("teamTbl");
  if(!tbl) return;
  if(!list || !list.length){
    tbl.innerHTML = '<tr><td colspan="5"><div class="empty-state"><i class="bi bi-person-badge"></i></div></td></tr>';
    return;
  }
  tbl.innerHTML = list.map(function(m){
    var perms = m.permissions||{};
    var permsHtml = TEAM_PERM_KEYS.filter(function(k){ return perms[k]; }).map(function(k){
      return '<span class="member-perm-badge">'+esc(_teamPermLabel(k))+'</span>';
    }).join("") || '<span style="color:var(--muted);font-size:11px">—</span>';
    var statusBadge = m.active!==false
      ? '<span class="badge bc">'+t("active")+'</span>'
      : '<span class="badge br">'+t("inactive")+'</span>';
    return '<tr>'+
      '<td><strong>'+esc(m.username)+'</strong></td>'+
      '<td>'+esc(m.name||m.username)+'</td>'+
      '<td style="white-space:normal;max-width:280px">'+permsHtml+'</td>'+
      '<td>'+statusBadge+'</td>'+
      '<td style="display:flex;gap:6px" data-user="'+esc(m.username)+'">'+
        '<button class="btn-outline btn-sm" onclick="openEditMemberModal(this.closest(\'td\').dataset.user)"><i class="bi bi-pencil"></i></button>'+
        '<button class="btn-danger" onclick="deleteTeamMember(this.closest(\'td\').dataset.user)"><i class="bi bi-trash"></i></button>'+
      '</td>'+
    '</tr>';
  }).join("");
}

function _renderPermCheckboxes(selected){
  selected = selected || {};
  var box = document.getElementById("tm_perms");
  box.innerHTML = TEAM_PERM_KEYS.map(function(k){
    var checked = selected[k] ? " checked" : "";
    return '<label class="perm-chip"><input type="checkbox" class="tm-perm-cb" value="'+k+'"'+checked+'/> '+_teamPermLabel(k)+'</label>';
  }).join("");
}

function _collectPermCheckboxes(){
  var out = {};
  document.querySelectorAll(".tm-perm-cb").forEach(function(cb){
    out[cb.value] = cb.checked;
  });
  return out;
}

function openAddMemberModal(){
  if(TEAM_MEMBERS.length >= TEAM_MAX){ toast("❌ "+t("team_count_of")+" "+TEAM_MAX,"err"); return; }
  document.getElementById("teamModalTitle").textContent = t("add_member");
  document.getElementById("tm_original_username").value = "";
  document.getElementById("tm_username").value = "";
  document.getElementById("tm_username").disabled = false;
  document.getElementById("tm_name").value = "";
  document.getElementById("tm_password").value = "";
  document.getElementById("tm_password").placeholder = "";
  document.getElementById("tm_password_hint").style.display = "none";
  document.getElementById("tm_active_wrap").style.display = "none";
  _renderPermCheckboxes({});
  openModal("teamMemberModal");
}

function openEditMemberModal(username){
  var m = TEAM_MEMBERS.find(function(x){ return x.username===username; });
  if(!m) return;
  document.getElementById("teamModalTitle").textContent = t("edit")+" — "+username;
  document.getElementById("tm_original_username").value = username;
  document.getElementById("tm_username").value = username;
  document.getElementById("tm_username").disabled = true;
  document.getElementById("tm_name").value = m.name||username;
  document.getElementById("tm_password").value = "";
  document.getElementById("tm_password_hint").style.display = "block";
  document.getElementById("tm_password_hint").textContent = t("leave_blank_password");
  document.getElementById("tm_active_wrap").style.display = "block";
  document.getElementById("tm_active").checked = m.active!==false;
  _renderPermCheckboxes(m.permissions||{});
  openModal("teamMemberModal");
}

async function saveTeamMember(){
  var originalUsername = document.getElementById("tm_original_username").value;
  var username = document.getElementById("tm_username").value.trim();
  var name     = document.getElementById("tm_name").value.trim();
  var password = document.getElementById("tm_password").value.trim();
  var perms    = _collectPermCheckboxes();
  if(!username){ toast("❌ "+t("member_username"),"err"); return; }
  var isEdit = !!originalUsername;
  if(!isEdit && !password){ toast("❌ "+t("member_password"),"err"); return; }
  try{
    var r;
    if(isEdit){
      var payload = {username: originalUsername, name: name, permissions: perms,
                      active: document.getElementById("tm_active").checked};
      if(password) payload.password = password;
      r = await apiPost("/team/updateMember", payload);
    } else {
      r = await apiPost("/team/addMember", {username:username, password:password, name:name, permissions:perms});
    }
    if(r.status==="ok"){
      toast("✅ "+t("save"),"ok");
      closeModal("teamMemberModal");
      loadTeam();
    } else {
      toast("❌ "+r.message,"err");
    }
  }catch(e){ toast("Erreur réseau","err"); }
}

async function deleteTeamMember(username){
  if(!confirm(t("confirm_delete_member"))) return;
  try{
    var r = await apiPost("/team/deleteMember", {username:username});
    if(r.status==="ok"){ toast("✅ "+t("delete"),"ok"); loadTeam(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast("Erreur réseau","err"); }
}

async function saveBotSettings(){
  var data = {
    Gemini_api_key:   document.getElementById("b_gemini").value.trim(),
    AI_instructions:  document.getElementById("b_inst").value.trim(),
    whtsapp_token:    document.getElementById("b_watoken").value.trim(),
    phone_number_id:  document.getElementById("b_phone_id").value.trim(),
    fb_access_token:  document.getElementById("b_fbtoken").value.trim(),
    page_id_FB:       document.getElementById("b_fbpage").value.trim(),
    instgram_access_token: document.getElementById("b_igtoken").value.trim(),
    Page_ID_instgram:      document.getElementById("b_igpage").value.trim(),
  };
  var r = await apiPost("/updateBotSettings", {data:data});
  if(r.status==="ok"){ toast("✅ "+t("save"),"ok"); }
  else { toast("❌ "+r.message,"err"); }
}

async function loadBotLogs(){
  var div = document.getElementById("botLogs");
  div.innerHTML = '<span class="spinner"></span>';
  try{
    var r = await apiPost("/saas", {action:"getBotLogs", limit:100});
    if(r.status==="ok"){
      var logs = r.data||[];
      if(!logs.length){ div.innerHTML='<div style="text-align:center;padding:20px;color:var(--muted)">Aucun log</div>'; return; }
      div.innerHTML = logs.map(function(l){
        var date     = l.date     || (l.timestamp ? new Date(l.timestamp*1000).toLocaleString("fr-DZ") : "—");
        var platform = l.platform || "FB";
        var userMsg  = l.user_message || l.user || "";
        var botReply = l.bot_reply   || l.bot  || "";
        var sender   = l.sender_id   ? '<span style="font-size:9px;color:var(--muted);margin-left:6px">'+esc(l.sender_id.substring(0,8))+'...</span>' : "";
        return '<div style="border-bottom:1px solid var(--border);padding:10px 0">'+
          '<div style="color:var(--muted);font-size:10px;margin-bottom:4px">'+esc(date)+' • '+esc(platform)+sender+'</div>'+
          (userMsg  ? '<div style="background:rgba(37,99,235,.08);border-radius:8px;padding:6px 10px;margin-bottom:4px;font-size:12px"><span style="color:var(--muted);font-size:10px">👤 Client</span><br>'+esc(userMsg.substring(0,200))+'</div>' : '')+
          (botReply ? '<div style="background:rgba(16,185,129,.08);border-radius:8px;padding:6px 10px;font-size:12px"><span style="color:var(--muted);font-size:10px">🤖 Bot</span><br>'+esc(botReply.substring(0,300))+'</div>' : '')+
        '</div>';
      }).join("");
    }
  }catch(e){ div.innerHTML='<div style="color:var(--red);padding:10px">Erreur: '+e.message+'</div>'; }
}

// =========================================================
// SETTINGS
// =========================================================
async function loadSettings(){
  document.getElementById("s_user").value = uname();
  document.getElementById("s_uid").value  = uid();
  document.getElementById("s_plan").value = currentPlan;
  fetchFbStatus("fbStatus");
}

async function fetchFbStatus(targetElId){
  var el = document.getElementById(targetElId);
  if(!el) return;
  try{
    var r = await fetch(FB_BACKEND+"/fb-status", {
      headers: authToken ? {"Authorization":"Bearer "+authToken} : {}
    });
    var d = await r.json();
    if(d.connected){
      el.innerHTML = '<span style="color:var(--green)"><i class="bi bi-check-circle"></i> Connecté</span> — '+(d.updated_at||"");
    } else {
      el.innerHTML = '<span style="color:var(--muted)"><i class="bi bi-x-circle"></i> Non connecté</span>';
    }
  }catch(e){}
}

async function connectFacebook(){
  // state موقّع من السيرفر (JWT) + nonce فكوكي HttpOnly مربوط بهاد المتصفح.
  // credentials:"include" باش المتصفح يحفظ الكوكي اللي يرسلها السيرفر مع الرد.
  var sr = {};
  try{
    var rr = await fetch(API_URL+"/getOAuthState", {
      credentials:"include",
      headers: authToken ? {"Authorization":"Bearer "+authToken} : {}
    });
    sr = await rr.json();
  }catch(e){}
  if(sr.status!=="ok"){ toast("❌ يرجى تسجيل الدخول من جديد","err"); return; }
  var state = encodeURIComponent(sr.data.state);
  var scope = "pages_manage_metadata,pages_read_engagement,pages_messaging,instagram_basic,instagram_manage_messages,ads_read";
  var oauthUrl = "https://www.facebook.com/v19.0/dialog/oauth?client_id="+FB_APP_ID_JS+
    "&redirect_uri="+encodeURIComponent(FB_BACKEND+"/callback")+
    "&scope="+scope+"&state="+state+"&response_type=code";
  var win = window.open(oauthUrl, "fbauth", "width=600,height=700,left=300,top=100");
  // الرسالة ما فيها حتى توكن: نتأكد غير من مصدرها، ومن بعد نعاود نجيب الحالة من السيرفر
  function reloadFromServer(){ loadSettings(); loadBot(); }
  function handler(ev){
    if(ev.origin!==FB_ORIGIN || ev.source!==win || !ev.data) return;
    if(ev.data.type==="FB_AUTH_SUCCESS"){
      toast("✅ Facebook connecté!","ok");
      window.removeEventListener("message", handler);
      reloadFromServer();
    }
    if(ev.data.type==="FB_AUTH_ERROR"){
      toast("❌ Erreur: "+String(ev.data.message||""),"err");
      window.removeEventListener("message", handler);
    }
  }
  window.addEventListener("message", handler);
  // احتياطي: إذا تسدّت النافذة بلا رسالة (المتصفح قطع window.opener)، نحدّث الحالة من السيرفر
  var poll = setInterval(function(){
    if(!win || win.closed){ clearInterval(poll); reloadFromServer(); }
  }, 1000);
}

async function disconnectFacebook(){
  if(!confirm("Déconnecter Facebook?")) return;
  await fetch(FB_BACKEND+"/fb-disconnect", {
    method:"POST",
    headers: authToken ? {"Authorization":"Bearer "+authToken} : {}
  });
  toast("✅ Déconnecté","ok");
  loadSettings();
}

async function checkFbStatus(){
  var el = document.getElementById("fbConnectStatus");
  var pl = document.getElementById("fbPagesList");
  var pc = document.getElementById("fbPagesContent");
  if(!el) return;
  el.textContent = "⏳ Vérification...";
  try{
    var r = await fetch(FB_BACKEND+"/fb-status", {
      headers: authToken ? {"Authorization":"Bearer "+authToken} : {}
    });
    var d = await r.json();
    if(d.connected){
      el.innerHTML = '<span style="color:var(--green)">✅ Connecté — '+esc(d.updated_at||"—")+'</span>';
      if(d.pages&&d.pages.length){
        pl.style.display="block";
        pc.innerHTML = d.pages.map(function(p){
          return '<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;background:var(--card2);border-radius:8px;margin-bottom:6px">'
            +'<span>'+(p.type==="instagram"?"📷":"📘")+'</span>'
            +'<div><div style="font-size:12px;font-weight:700">'+esc(p.name||"—")+'</div>'
            +'<div style="font-size:10px;color:var(--muted)">'+esc(p.type)+' · '+esc(p.id||"—")+'</div></div></div>';
        }).join("");
      } else { pl.style.display="none"; }
    } else {
      el.innerHTML = '<span style="color:var(--red)">❌ Non connecté</span>';
      if(pl) pl.style.display="none";
    }
  }catch(e){
    if(el) el.innerHTML = '<span style="color:var(--muted)">⚠️ Erreur serveur</span>';
  }
}
 

// =========================================================
// MODALS
// =========================================================
function openModal(id){
  document.getElementById(id).classList.add("show");
  if(id==="addOrderModal"){ prefillOrderSelects(); document.getElementById("o_delivery").value=""; }
  if(id==="addProductModal"){ currentProductImages = []; renderProductImageThumbs(); }
  if(id==="createLandingModal"){
    currentLandingImages = [];
    currentLandingQuestions = [];
    renderLandingImageThumbs();
    lp_backToStep1();
    var ctaSel = document.getElementById("lp_cta_type");
    if(ctaSel) ctaSel.value = "store";
    toggleLandingCtaFields();
  }
}
function closeModal(id){
  document.getElementById(id).classList.remove("show");
}
document.querySelectorAll(".modal-overlay").forEach(function(m){
  m.addEventListener("click", function(e){
    if(e.target===m) m.classList.remove("show");
  });
});

// =========================================================
// تحديث الطلبات الدوري (Polling) — يحل محل SSE المباشر على Firebase
// (كان يكشف مفتاح قاعدة البيانات السري للمتصفح؛ الآن يمر عبر API محمي بتوكن)
// =========================================================
function startOrdersPolling(){
  stopOrdersPolling();
  _ordersPollTimer = setInterval(pollOrders, 10000);
}
// رجوع للتبويب: تحديث فوري بدل ما نستناو الدورة الجاية
document.addEventListener("visibilitychange", function(){
  if(!document.hidden && _ordersPollTimer) pollOrders();
});
function stopOrdersPolling(){
  if(_ordersPollTimer){ clearInterval(_ordersPollTimer); _ordersPollTimer = null; }
}

// =========================================================
// رفع الصور — دالة مشتركة واحدة (تحل محل التكرار السابق بين
// رفع صورة منتج وصورة متجر)، تمر عبر السيرفر (Admin SDK)
// =========================================================
async function _uploadImageFile(file){
  var fd = new FormData();
  fd.append("file", file);
  var res = await fetch(API_URL+"/uploadImage", {
    method:"POST",
    headers: authToken ? {"Authorization":"Bearer "+authToken} : {},
    body: fd
  });
  var data = await res.json();
  if(data.status!=="ok") throw new Error(data.message||"upload failed");
  return data.data.url;
}

var currentProductImages = [];

function renderProductImageThumbs(){
  var wrap = document.getElementById("p_img_thumbs");
  wrap.innerHTML = currentProductImages.map(function(url, i){
    return '<div class="thumb-item"><img src="'+url+'"/><button class="rm" onclick="removeProductImage('+i+')">✕</button></div>';
  }).join("");
}

function removeProductImage(i){
  currentProductImages.splice(i,1);
  renderProductImageThumbs();
}

async function addProductImages(input){
  var files = Array.prototype.slice.call(input.files||[]).slice(0, 4 - currentProductImages.length);
  if(!files.length) return;
  var statusEl = document.getElementById("p_img_upload_status");
  statusEl.textContent = "⏳ جاري الرفع..."; statusEl.style.color = "var(--yellow)";
  try{
    for(var i=0;i<files.length;i++){
      var url = await _uploadImageFile(files[i]);
      currentProductImages.push(url);
    }
    renderProductImageThumbs();
    statusEl.textContent = "✅ تم الرفع بنجاح"; statusEl.style.color = "var(--green)";
  }catch(e){
    statusEl.textContent = "❌ فشل الرفع"; statusEl.style.color = "var(--red)";
    console.error("Upload error:", e);
  }
}

async function uploadStoreProductImage(input, productName) {
  var file = input.files[0];
  if (!file) return;
  var label = input.parentElement;
  var origText = label.childNodes[0].textContent;
  label.childNodes[0].textContent = "⏳ ...";
  try {
    var url = await _uploadImageFile(file);
    var r = await apiPost("/addProduct",{data:{name:productName,image:url}});
    if(r.status==="ok"){
      toast("✅ صورة "+productName+" محدّثة","ok");
      loadStore();
    } else throw new Error(r.message||"error");
  } catch(e) {
    toast("❌ فشل رفع الصورة","err");
    label.childNodes[0].textContent = origText;
    console.error(e);
  }
}

// =========================================================
// PUBLIC SHOP — متجر عام (بدون مصادقة، عبر المسارات العامة فقط)
// =========================================================
var SHOP_UID = null;
var SHOP_PRODUCTS = [];
var SHOP_CITIES   = [];
var SHOP_CART     = [];
var SHOP_CURRENCY = "DZD";
var SHOP_CATEGORY = "";
var PDP_PRODUCT   = null;
var PDP_IMG_IDX   = 0;

(function(){
  var p = new URLSearchParams(window.location.search);
  var s = p.get("store");
  if(s){
    SHOP_UID = s;
    initShop();
  }
})();

function initShop(){
  document.getElementById("loginPage").style.display  = "none";
  document.getElementById("shopApp").style.display    = "block";
  document.getElementById("sidebar") && (document.getElementById("sidebar").style.display="none");
  document.getElementById("main")    && (document.getElementById("main").style.display="none");
  document.body.style.display = "block";
  loadShopData();
  document.getElementById("sh-search").addEventListener("input", function(){ sh_renderGrid(this.value); });
}

async function loadShopData(){
  try{
    var pr = await apiGet("/getStoreProducts", {userId: SHOP_UID}, false);
    var cr = await apiGet("/getStoreCities",   {userId: SHOP_UID}, false);
    var sr = await apiGet("/getStoreSettings", {userId: SHOP_UID}, false);

    SHOP_PRODUCTS = (pr.status==="ok" && pr.data) ? pr.data.filter(function(p){ return p.visible!=="no"; }) : [];
    SHOP_CITIES   = (cr.status==="ok" && cr.data) ? cr.data : [];

    if(sr.status==="ok" && sr.data){
      var s = sr.data;
      SHOP_CURRENCY = s.currency || "DZD";
      document.getElementById("sh-logo").innerHTML = s.logoImage
        ? '<img src="'+esc(s.logoImage)+'" style="width:100%;height:100%;object-fit:cover;border-radius:10px"/>'
        : esc(s.logo||"🛒");
      document.getElementById("sh-name").textContent = s.name||"Boutique";
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
  box.innerHTML = '<span class="shop-chip'+(SHOP_CATEGORY===""?" active":"")+'" data-cat="" onclick="sh_filterCategory(this.dataset.cat)">الكل</span>' +
    cats.map(function(c){
      return '<span class="shop-chip'+(SHOP_CATEGORY===c?" active":"")+'" data-cat="'+esc(c)+'" onclick="sh_filterCategory(this.dataset.cat)">'+esc(c)+'</span>';
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
                [1,2,3,4,5].map(function(n){ return '<span data-n="'+n+'" onclick="setRateStar(this,parseInt(this.dataset.n))">☆</span>'; }).join("")+
              '</div>'+
              '<textarea class="rate-comment" placeholder="تعليق (اختياري)"></textarea>'+
              '<button class="btn-primary btn-sm" style="margin-top:8px" onclick="submitProductRating(this.closest(\'.rate-widget\').dataset.orderId,this)">إرسال التقييم</button>'+
            '</div>';
          }
        }
        return '<div class="track-result"><div style="display:flex;justify-content:space-between;align-items:center">'+
          '<div><strong>'+esc(o.product)+'</strong> × '+esc(o.qty)+'<div style="font-size:11px;color:var(--muted)">'+esc(o.date)+'</div></div>'+
          '<span class="badge '+stCls+'">'+esc(o.status)+'</span></div>'+rateBlock+'</div>';
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
  if(!list.length){ grid.innerHTML=""; empty.style.display="block"; return; }
  empty.style.display="none";
  grid.innerHTML = list.map(function(p){
    var av  = Number(p.available||0);
    var dis = av<=0;
    var img = p.image
      ? '<img src="'+esc(p.image)+'" onerror="this.style.display=\'none\'" style="width:100%;height:100%;object-fit:cover"/>'
      : '📦';
    return '<div class="shop-card" data-name="'+esc(p.name)+'" onclick="pdp_open(this.dataset.name)" style="cursor:pointer">'+
      '<div class="shop-card-img">'+img+'</div>'+
      '<div class="shop-card-body">'+
        '<div class="shop-card-name">'+esc(p.name)+'</div>'+
        (p.category?'<div class="shop-card-cat">'+esc(p.category)+'</div>':'')+
        starsHtml(p.avgRating, p.ratingCount)+
        (p.description?'<div style="font-size:11px;color:var(--muted);margin-top:4px">'+esc(p.description)+'</div>':'')+
        (av>0 && av<=5?'<div style="font-size:11px;color:var(--red);font-weight:700;margin-top:4px">⚡ متبقي '+av+' قطع فقط!</div>':'')+
      '</div>'+
      '<div class="shop-card-footer">'+
        '<div class="shop-price">'+esc(p.sell||0)+' '+sh_cur()+'</div>'+
        '<button class="shop-add-btn"'+(dis?' disabled':'')+' data-name="'+esc(p.name)+'" onclick="event.stopPropagation();sh_addToCart(this.dataset.name)">'+
        (dis?'Rupture':'🛒 Ajouter')+'</button>'+
      '</div></div>';
  }).join("");
}

// ── Product Detail Modal (PDP) ──────────────────────────
function pdp_open(name){
  var p = SHOP_PRODUCTS.find(function(x){ return x.name===name; });
  if(!p) return;
  PDP_PRODUCT = p;
  PDP_IMG_IDX = 0;
  var av = Number(p.available||0);
  document.getElementById("pdp-cat").textContent = p.category||"";
  document.getElementById("pdp-name").textContent = p.name;
  document.getElementById("pdp-stars").innerHTML = starsHtml(p.avgRating, p.ratingCount);
  document.getElementById("pdp-price").textContent = (p.sell||0)+" "+sh_cur();
  document.getElementById("pdp-desc").textContent = p.description||"";
  document.getElementById("pdp-reviews").style.display = "none";
  document.getElementById("pdp-reviews").innerHTML = "";
  var stCls = av<=0?"br":av<=5?"bn":"bc";
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
function pdp_renderImage(){
  var imgs = (PDP_PRODUCT.images && PDP_PRODUCT.images.length) ? PDP_PRODUCT.images : (PDP_PRODUCT.image?[PDP_PRODUCT.image]:[]);
  var img = document.getElementById("pdp-img");
  var fb  = document.getElementById("pdp-img-fallback");
  if(imgs.length){
    img.src = imgs[PDP_IMG_IDX]; img.style.display="block"; fb.style.display="none";
  } else {
    img.style.display="none"; fb.style.display="block";
  }
  document.getElementById("pdp-dots").innerHTML = imgs.map(function(_,i){
    return '<span class="pdp-dot'+(i===PDP_IMG_IDX?" active":"")+'"></span>';
  }).join("");
}
function pdp_nav(dir){
  var imgs = (PDP_PRODUCT.images && PDP_PRODUCT.images.length) ? PDP_PRODUCT.images : (PDP_PRODUCT.image?[PDP_PRODUCT.image]:[]);
  if(!imgs.length) return;
  PDP_IMG_IDX = (PDP_IMG_IDX + dir + imgs.length) % imgs.length;
  pdp_renderImage();
}
function pdp_addToCart(){
  if(PDP_PRODUCT) sh_addToCart(PDP_PRODUCT.name);
  closePdp();
}
function closePdp(){
  document.getElementById("pdpOverlay").classList.remove("open");
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
          '<button class="cart-qty-btn" data-name="'+esc(c.name)+'" onclick="sh_changeQty(this.dataset.name,-1)">−</button>'+
          '<span style="font-weight:700;min-width:20px;text-align:center">'+c.qty+'</span>'+
          '<button class="cart-qty-btn" data-name="'+esc(c.name)+'" onclick="sh_changeQty(this.dataset.name,1)">+</button>'+
        '</div>'+
        '<button data-name="'+esc(c.name)+'" onclick="sh_removeFromCart(this.dataset.name)" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:16px;padding:4px">🗑️</button>'+
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

// =========================================================
// THEME TOGGLE — وضع النهار / الليل
// =========================================================
var DARK_MODE = localStorage.getItem("of_theme") !== "light";

function applyTheme(){
  var pill = document.getElementById("themePill");
  var dot  = document.getElementById("themeDot");
  var lbl  = document.getElementById("themeLabel");
  if(DARK_MODE){
    document.documentElement.style.removeProperty("--bg");
    document.documentElement.style.removeProperty("--sidebar");
    document.documentElement.style.removeProperty("--card");
    document.documentElement.style.removeProperty("--card2");
    document.documentElement.style.removeProperty("--text");
    document.documentElement.style.removeProperty("--muted");
    document.documentElement.style.removeProperty("--border");
    if(pill){ pill.style.background="rgba(255,255,255,.12)"; }
    if(dot){  dot.style.transform="translateX(0)"; }
    if(lbl){  lbl.textContent="☀️ Mode Clair"; }
  } else {
    document.documentElement.style.setProperty("--bg",      "#f0f4f8");
    document.documentElement.style.setProperty("--sidebar", "#ffffff");
    document.documentElement.style.setProperty("--card",    "#ffffff");
    document.documentElement.style.setProperty("--card2",   "#f8fafc");
    document.documentElement.style.setProperty("--text",    "#1e293b");
    document.documentElement.style.setProperty("--muted",   "#64748b");
    document.documentElement.style.setProperty("--border",  "rgba(0,0,0,0.09)");
    if(pill){ pill.style.background="#2563eb"; }
    if(dot){  dot.style.transform="translateX(15px)"; }
    if(lbl){  lbl.textContent="🌙 Mode Sombre"; }
  }
  var activeSec = document.querySelector(".section.active");
  if(activeSec && activeSec.id==="sec_dashboard" && currentUser) loadDashboard();
}

function toggleTheme(){
  DARK_MODE = !DARK_MODE;
  localStorage.setItem("of_theme", DARK_MODE ? "dark" : "light");
  applyTheme();
}

// =========================================================
// INIT
// =========================================================
applyTheme();
applyLang(currentLang);
restoreSession();

// حماية من bfcache: لو المتصفح رجّع نسخة محفوظة من الصفحة (زر "رجوع")
// بدون ?store= بالرابط، نتأكد السايدبار وMain ظاهرين بالشكل الصحيح
window.addEventListener("pageshow", function(e){
  if(!SHOP_UID){
    var sb = document.getElementById("sidebar"), mn = document.getElementById("main");
    if(sb) sb.style.display = "";
    if(mn) mn.style.display = "";
    document.getElementById("shopApp").style.display = "none";
  }
});
