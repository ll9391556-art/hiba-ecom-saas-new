// =========================================================
// MODALS
// =========================================================
function openModal(id){
  document.getElementById(id).classList.add("show");
  if(id==="addOrderModal"){ prefillOrderSelects(); document.getElementById("o_delivery").value=""; }
  if(id==="addProductModal"){ currentProductImages = []; renderProductImageThumbs(); setProductEditMode(null); }
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
async function _uploadImageFile(file, path){
  var fd = new FormData();
  fd.append("file", file);
  var res = await fetch(API_URL+(path||"/uploadImage"), {
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
    return '<div class="thumb-item"><img src="'+esc(url)+'"/><button class="rm" data-i="'+i+'" data-on-click="removeProductImage(Number(this.dataset.i))">✕</button></div>';
  }).join("");
}

function removeProductImage(i){
  currentProductImages.splice(i,1);
  renderProductImageThumbs();
}

async function addProductImages(input){
  var files = Array.prototype.slice.call(input.files||[]).slice(0, 5 - currentProductImages.length);
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
    // تبدّل الصورة الأولى فـ image و images مع بعض (السلايدر يقرا images)، والباقي يبقى
    var rest = (STORE_PRODUCT_IMAGES[productName]||[]).slice(1);
    var r = await apiPost("/addProduct",{data:{name:productName,image:url,images:[url].concat(rest).slice(0,5)}});
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

