// =========================================================
// CONFIG
// =========================================================
var API_URL    = "https://orderconfidence.com/api";
var FB_BACKEND = "https://orderconfidence.com";
var FB_ORIGIN  = new URL(FB_BACKEND).origin;  // صفحة /callback تبعث postMessage غير من هنا
var FB_APP_ID_JS = "1484940433173462";
// متجر عام (/?store=<uid>): shop.js يعمّرها؛ اللوحة (auth.js، main.js) كتقراها — لذلك هنا
var SHOP_UID = null;
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
var PLAN_FEATURES = {};
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
    return '<button class="lang-btn'+(code===merchantCurrency?" active":"")+'" data-code="'+esc(code)+'" data-on-click="setMerchantCurrency(this.dataset.code)">'+esc(code)+'</button>';
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
    unit_month:"DZD/mois",unit_year:"DZD/an",or_yearly:"ou",plan_early:"Premiers marchands",
    pf_products:"Produits et stock",pf_cities:"Wilayas et livraison",pf_all_free:"Tout Free",pf_tracking:"Suivi des commandes",
    pf_export:"Export Excel",pf_templates2:"2 modèles de boutique",pf_templates_all:"Tous les modèles",pf_landing:"Landing pages",
    pf_coupons:"Coupons de réduction",pf_team:"Comptes d'équipe",pf_bot_1500:"Bot AI — 1 500 réponses/mois",
    pf_bot_5000:"Bot AI — 5 000 réponses/mois",pf_early_pro:"Pro complet pendant 1 an",pf_early_slots:"Réservé aux 50 premiers marchands",
    plan_payment:"Paiement par BaridiMob ou CCP — le plan est activé par l'administration après paiement.",
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
    unit_month:"DZD/شهر",unit_year:"DZD/سنة",or_yearly:"أو",plan_early:"أوائل التجار",
    pf_products:"المنتجات والمخزون",pf_cities:"الولايات والتوصيل",pf_all_free:"كل ميزات Free",pf_tracking:"تتبع الطلبات",
    pf_export:"تصدير Excel",pf_templates2:"قالبين للمتجر",pf_templates_all:"كل القوالب",pf_landing:"صفحات هبوط",
    pf_coupons:"كوبونات تخفيض",pf_team:"حسابات الفريق",pf_bot_1500:"بوت AI — 1,500 رد/شهر",
    pf_bot_5000:"بوت AI — 5,000 رد/شهر",pf_early_pro:"Pro كاملة لمدة عام",pf_early_slots:"لأول 50 تاجر فقط",
    plan_payment:"الدفع عبر BaridiMob أو CCP — بعد الدفع تتفعّل الباقة من الإدارة.",
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
    unit_month:"DZD/month",unit_year:"DZD/year",or_yearly:"or",plan_early:"Early merchants",
    pf_products:"Products and stock",pf_cities:"Wilayas and delivery",pf_all_free:"All Free features",pf_tracking:"Order tracking",
    pf_export:"Excel export",pf_templates2:"2 store templates",pf_templates_all:"All templates",pf_landing:"Landing pages",
    pf_coupons:"Discount coupons",pf_team:"Team accounts",pf_bot_1500:"AI Bot — 1,500 replies/month",
    pf_bot_5000:"AI Bot — 5,000 replies/month",pf_early_pro:"Full Pro for 1 year",pf_early_slots:"First 50 merchants only",
    plan_payment:"Pay by BaridiMob or CCP — the admin activates your plan after payment.",
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
// EVENTS — بدل onclick="..." inline (Phase 4 / F5): data-on-<event>="نص الـ handler"
// + جدول ACTIONS (static/js/actions.js أو registerActions فالصفحة). مستمع واحد لكل حدث
// على document كيمشي من العنصر لفوق: كل عنصر عندو data-on-<event> كيتنفّذ (this = العنصر)،
// ويوقف إذا الـ handler دار event.stopPropagation() — نفس سلوك الـ inline. error ديال
// الصور ما كيصعدش، لذلك كيتسمع فمرحلة capture. بلا eval → يسمح بـ CSP صارمة من بعد.
// =========================================================
var ACTIONS = {};
function registerActions(map){
  for(var k in map) if(Object.prototype.hasOwnProperty.call(map, k)) ACTIONS[k] = map[k];
}
["click", "change", "input", "keydown", "error"].forEach(function(type){
  var attr = "data-on-" + type;
  document.addEventListener(type, function(event){
    for(var el = event.target; el && el.nodeType === 1; el = el.parentNode){
      if(!el.hasAttribute(attr)) continue;
      var fn = ACTIONS[el.getAttribute(attr)];
      if(fn && fn.call(el, event) === false) event.preventDefault();
      if(event.cancelBubble || type === "error") break;
    }
  }, type === "error");
});
