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
      document.getElementById("ss_currency").value = s.currency||"DZD";
      currentStoreLogoImage = s.logoImage||"";
      renderStoreLogoPreview();
    }
    var pr = await apiGet("/getStoreProducts", {userId: uid()}, false);
    var grid = document.getElementById("storeGrid");
    if(pr.status==="ok"){
      var cur = curSym();
      STORE_PRODUCT_IMAGES = {};
      (pr.data||[]).forEach(function(p){ STORE_PRODUCT_IMAGES[p.name] = p.images||[]; });
      grid.innerHTML = (pr.data||[]).filter(function(p){ return p.visible!=="no"; }).map(function(p){
        var stCls = {"In Stock":"bs","Low Stock":"bn","Out of Stock":"br"}[p.stat]||"bp";
        return '<div class="store-card">'+
          '<div style="position:relative">'+
            (p.image
              ? '<img src="'+esc(p.image)+'" alt="'+esc(p.name)+'" style="width:100%;height:160px;object-fit:cover" data-on-error="this.style.display=\'none\'"/>'
              : '<div style="height:160px;display:flex;align-items:center;justify-content:center;background:var(--card2);font-size:40px">📦</div>')+
            '<label style="position:absolute;bottom:8px;right:8px;background:var(--accent);color:#fff;padding:5px 10px;border-radius:6px;font-size:11px;cursor:pointer;font-weight:600;display:inline-flex;align-items:center;gap:4px">'+
              '📸 Changer'+
              '<input type="file" accept="image/*" style="display:none" data-name="'+esc(p.name)+'" data-on-change="uploadStoreProductImage(this,this.dataset.name)"/>'+
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
var STORE_PRODUCT_IMAGES  = {};  // اسم المنتج → images (لزر "📸 Changer")

function renderStoreLogoPreview(){
  var box = document.getElementById("ss_logo_preview");
  if(!box) return;
  box.innerHTML = currentStoreLogoImage
    ? '<div class="thumb-item"><img src="'+esc(currentStoreLogoImage)+'"/><button class="rm" data-on-click="removeStoreLogoImage()">✕</button></div>'
    : '';
}

function removeStoreLogoImage(){
  currentStoreLogoImage = "";
  renderStoreLogoPreview();
}

async function uploadStoreLogoImage(input){
  var file = input.files[0];
  if(!file) return;
  // نفس شروط السيرفر (اللي يعاود يتحقق): PNG/JPG/WEBP، حتى 1MB
  if(["image/png","image/jpeg","image/webp"].indexOf(file.type)===-1){ toast("❌ PNG / JPG / WEBP","err"); input.value=""; return; }
  if(file.size > 1024*1024){ toast("❌ 1MB max","err"); input.value=""; return; }
  var box = document.getElementById("ss_logo_preview");
  box.innerHTML = '<span class="spinner"></span>';
  try{
    currentStoreLogoImage = await _uploadImageFile(file, "/uploadStoreLogo");
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
    logoImage:currentStoreLogoImage,
    currency: document.getElementById("ss_currency").value,
  }});
  if(r.status==="ok"){
    merchantCurrency = document.getElementById("ss_currency").value;
    renderCurrencyButtons();
    toast("✅ "+t("saved"),"ok"); closeModal("storeSettingsModal"); loadStore();
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
    return '<div class="thumb-item"><img src="'+url+'"/><button class="rm" data-i="'+i+'" data-on-click="removeLandingImage(Number(this.dataset.i))">✕</button></div>';
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
  }catch(e){ toast(t("network_error"),"err"); }
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
  }catch(e){ toast(t("network_error"),"err"); }
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
    var img = (p.images&&p.images[0]) ? '<img src="'+esc(p.images[0])+'" style="width:100%;height:160px;object-fit:cover" data-on-error="this.style.display=\'none\'"/>'
                                       : '<div style="height:160px;display:flex;align-items:center;justify-content:center;background:var(--card2);font-size:40px">🎯</div>';
    var pubBadge = p.published ? '<span class="badge bs">'+t("landing_published")+'</span>' : '<span class="badge bp">'+t("landing_unpublished")+'</span>';
    var igBadge  = p.instagramPostId ? '<span class="badge bi" style="margin-right:4px">📷 IG</span>' : '';
    return '<div class="store-card">'+
      img+
      '<div class="store-card-body">'+
        '<div class="store-card-title">'+esc(p.name)+'</div>'+
        '<div style="font-size:11px;color:var(--muted);margin:4px 0">'+esc(p.created_at||"")+' · 👁️ '+esc(p.views||0)+' '+t("landing_views")+'</div>'+
        '<div style="margin-bottom:8px">'+pubBadge+' '+igBadge+'</div>'+
        '<div style="display:flex;gap:6px;flex-wrap:wrap" data-id="'+esc(p.id)+'" data-url="'+esc(p.publicUrl)+'">'+
          '<button class="btn-outline btn-sm" data-on-click="window.open(this.closest(\'div[data-url]\').dataset.url,\'_blank\')"><i class="bi bi-eye"></i> '+t("landing_preview")+'</button>'+
          '<button class="btn-outline btn-sm" data-on-click="copyLandingLink(this.closest(\'div[data-url]\').dataset.url)"><i class="bi bi-clipboard"></i> '+t("landing_copy_link")+'</button>'+
          '<button class="btn-success" data-on-click="toggleLandingPublish(this.closest(\'div[data-id]\').dataset.id)">'+(p.published?'⏸️':'▶️')+'</button>'+
          '<button class="btn-primary btn-sm" data-on-click="postLandingToInstagram(this.closest(\'div[data-id]\').dataset.id)"><i class="bi bi-instagram"></i> '+t("landing_post_ig")+'</button>'+
          '<button class="btn-danger" data-on-click="deleteLandingPage(this.closest(\'div[data-id]\').dataset.id)"><i class="bi bi-trash"></i></button>'+
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
  }catch(e){ toast(t("network_error"),"err"); }
}

async function deleteLandingPage(pageId){
  if(!confirm(t("landing_delete_confirm"))) return;
  try{
    var r = await apiPost("/landing/delete", {pageId:pageId});
    if(r.status==="ok"){ toast("✅ "+t("delete"),"ok"); loadLanding(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast(t("network_error"),"err"); }
}

async function postLandingToInstagram(pageId){
  if(!confirm(t("landing_post_ig_confirm"))) return;
  try{
    var r = await apiPost("/landing/postToInstagram", {pageId:pageId});
    if(r.status==="ok"){ toast("✅ تم النشر على إنستغرام","ok"); loadLanding(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast(t("network_error"),"err"); }
}

