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
        '<select class="status-sel" data-id="'+safeId+'" data-on-change="updateOrderDelivery(this.dataset.id,this.value)">'+
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
        '<select class="status-sel" data-on-change="updateStatus(this.dataset.id,this.value)" data-id="'+safeId+'">'+opts+'</select>'+
      '</td>'+
      '<td><button class="btn-outline btn-sm" data-id="'+safeId+'" data-on-click="printOrderSlip(this.dataset.id)" title="طباعة بون دو كوموند"><i class="bi bi-printer"></i></button></td>'+
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

