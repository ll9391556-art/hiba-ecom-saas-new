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

function _dropOrders(ids){
  var changed = false;
  (ids||[]).forEach(function(id){ if(ORDERS_BY_ID[id]){ delete ORDERS_BY_ID[id]; changed = true; } });
  if(changed) _mergeOrders([], true);
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
    } else { tbl.innerHTML='<tr><td colspan="15" class="empty-state">'+esc(r.message||t("error"))+'</td></tr>'; }
  }catch(e){ tbl.innerHTML='<tr><td colspan="15" class="empty-state">'+t("error")+'</td></tr>'; }
}

async function loadOlderOrders(){
  if(!ORDERS_HAS_MORE || ORDERS_OLDEST===null) return;
  try{
    var r = await apiGet("/getOrders", {limit: ORDERS_PAGE, before: ORDERS_OLDEST});
    if(r.status==="ok"){ _applyOrdersPage(r); filterOrders(); }
    else toast("❌ "+(r.message||t("error")),"err");
  }catch(e){ toast(t("network_error"),"err"); }
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
    var dropped = r.deleted && r.deleted.length ? _dropOrders(r.deleted) : false;  // تحذفو من تبويب آخر
    if((r.data && r.data.length && _mergeOrders(r.data, false)) || dropped) filterOrders();
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
      return '<option value="'+s+'"'+(o.status===s?" selected":"")+'>'+stLabel(s)+'</option>';
    }).join("");
    var safeId = esc(o.id);
    // تحت 640px نفس السطر يولّي بطاقة (CSS، D3.5): class لكل خانة، وdataLabel() مترجم يبان فوقها
    return '<tr>'+
      '<td class="oc-num">'+(i+1)+'</td>'+
      '<td class="oc-date" style="font-size:11px"><span class="m-only oc-id" dir="ltr">'+safeId+'</span>'+esc(o.date||"—")+'</td>'+
      '<td class="oc-name"'+dataLabel("client")+'><strong>'+esc(o.name||"—")+'</strong></td>'+
      '<td class="oc-phone"'+dataLabel("phone")+'><a href="tel:'+esc(o.phone||"")+'" style="color:var(--accent)" dir="ltr">'+esc(o.phone||"—")+'</a></td>'+
      '<td class="oc-product"'+dataLabel("product")+'>'+esc(o.product||"—")+'</td>'+
      '<td class="oc-qty"'+dataLabel("qty")+'>'+esc(o.qty||1)+'</td>'+
      '<td class="oc-city"'+dataLabel("city")+'>'+esc(o.city||"—")+'</td>'+
      '<td class="oc-delivery"'+dataLabel("delivery_col")+'>'+
        '<span class="badge bn me-1">'+(o.deliveryType==="desk"?t("desk_short"):t("home_short"))+'</span>'+
        '<select class="status-sel" data-id="'+safeId+'" data-on-change="updateOrderDelivery(this.dataset.id,this.value)">'+
          '<option value="home"'+(o.deliveryType!=="desk"?" selected":"")+'>'+t("home_delivery")+'</option>'+
          '<option value="desk"'+(o.deliveryType==="desk"?" selected":"")+'>'+t("desk_delivery")+'</option>'+
        '</select>'+
      '</td>'+
      '<td class="oc-total"'+dataLabel("total")+'><strong>'+esc(o.total||0)+' '+cur+'</strong></td>'+
      '<td class="oc-profit"'+dataLabel("profit")+' style="color:'+(parseFloat(o.profit||0)>=0?"var(--green)":"var(--red)")+'">'+esc(o.profit||0)+' '+cur+'</td>'+
      '<td class="oc-source"><span class="badge bn">'+esc(o.source||"manual")+'</span></td>'+
      '<td class="oc-sent" style="font-size:11px;color:var(--muted)">'+esc(o.date_sent||"—")+'</td>'+
      '<td class="oc-delivered" style="font-size:11px;color:var(--muted)">'+esc(o.date_delivered||"—")+'</td>'+
      '<td class="oc-status"'+dataLabel("status")+'>'+
        '<span class="badge '+stCls+' me-1">'+esc(stLabel(o.status))+'</span>'+
        '<select class="status-sel" data-on-change="updateStatus(this.dataset.id,this.value)" data-id="'+safeId+'">'+opts+'</select>'+
      '</td>'+
      '<td class="oc-actions">'+
        '<button class="btn-outline btn-sm btn-icon" data-id="'+safeId+'" data-on-click="printOrderSlip(this.dataset.id)" title="'+esc(t("print_slip"))+'" aria-label="'+esc(t("print_slip"))+'"><i data-lucide="printer"></i></button>'+
        '<button class="btn-outline btn-sm btn-icon" data-id="'+safeId+'" data-on-click="openOrderEdit(this.dataset.id)" title="'+esc(t("edit"))+'" aria-label="'+esc(t("edit"))+'"><i data-lucide="pencil"></i></button>'+
        // الحذف للمالك برك (السيرفر يرفض العضو بـ 403)
        (currentRole==="owner" ? '<button class="btn-danger btn-sm btn-icon" data-id="'+safeId+'" data-on-click="deleteOrder(this.dataset.id)" title="'+esc(t("delete"))+'" aria-label="'+esc(t("delete"))+'"><i data-lucide="trash-2"></i></button>' : '')+
      '</td>'+
    '</tr>';
  }).join("");
  drawIcons();
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
      toast("✅ "+t("status_updated").replace("{s}", stLabel(newStatus)), "ok");
      var o = allOrders.find(function(x){ return x.id===orderId; });
      if(o){
        o.status = newStatus;
        var now = new Date().toLocaleString("fr-DZ");
        if(newStatus==="Confirmed" && !o.date_sent)   o.date_sent      = now;
        if(newStatus==="Delivered" && !o.date_delivered) o.date_delivered = now;
      }
      renderOrders(allOrders);
    } else { toast("❌ "+r.message, "err"); }
  }catch(e){ toast(t("network_error"),"err"); }
}

async function updateOrderDelivery(orderId, newType){
  try{
    var r = await apiPost("/updateOrderDelivery", {orderId:orderId, deliveryType:newType});
    if(r.status==="ok"){
      toast("✅ تم تحديث نوع التوصيل","ok");
      loadOrders(); // إعادة تحميل لضمان دقة الإجمالي والربح المُعاد حسابهما من السيرفر
    } else { toast("❌ "+r.message, "err"); }
  }catch(e){ toast(t("network_error"),"err"); }
}

// ── تعديل وحذف طلبية (المهمة 3) ──
var EDIT_ORDER_ID     = null;
var EDIT_ORDER_TOTAL0 = "";   // المجموع كيما تفتح المودال: إذا ما تبدّلش، السيرفر يحسبو وحدو
var EDIT_ORDER_TOTAL_OPEN = ""; // المجموع المخزّن، يرجع كي التاجر يرجّع الخانات كيما كانو
var EDIT_TOTAL_MANUAL = false;  // التاجر كتب المجموع بيدو: ما نبدّلوهش
var EDIT_PRICES = {products:{}, cities:{}};  // بالاسم، من getProducts/getCities

// القائمة + القيمة الحالية حتى لو ماعادتش (طلبية قديمة بمنتج ولا ولاية محذوفين)
function _fillSelect(sel, names, current){
  var list = names.slice();
  if(current && list.indexOf(current)<0) list.unshift(current);
  sel.innerHTML = list.map(function(n){
    return '<option value="'+esc(n)+'"'+(n===current?" selected":"")+'>'+esc(n)+'</option>';
  }).join("");
}

async function openOrderEdit(orderId){
  var o = ORDERS_BY_ID[orderId];
  if(!o){ toast(t("error"),"err"); return; }
  EDIT_ORDER_ID = orderId;
  document.getElementById("e_title_id").textContent = orderId;
  document.getElementById("e_name").value     = o.name||"";
  document.getElementById("e_phone").value    = o.phone||"";
  document.getElementById("e_qty").value      = o.qty||1;
  document.getElementById("e_delivery").value = o.deliveryType==="desk" ? "desk" : "home";
  document.getElementById("e_status").innerHTML = ["Pending","Confirmed","Delivered","Refused","No Answer"].map(function(s){
    return '<option value="'+s+'"'+(o.status===s?" selected":"")+'>'+esc(stLabel(s))+'</option>';
  }).join("");
  EDIT_ORDER_TOTAL0 = String(o.total===undefined||o.total===null ? "" : o.total);
  EDIT_ORDER_TOTAL_OPEN = EDIT_ORDER_TOTAL0;
  EDIT_TOTAL_MANUAL = false;
  EDIT_PRICES = {products:{}, cities:{}};
  document.getElementById("e_total").value = EDIT_ORDER_TOTAL0;
  _fillSelect(document.getElementById("e_product"), [], o.product||"");
  _fillSelect(document.getElementById("e_city"), [], o.city||"");
  openModal("editOrderModal");
  try{
    var pr = await apiGet("/getProducts", {}), cr = await apiGet("/getCities", {});
    if(EDIT_ORDER_ID!==orderId) return;
    if(pr.status==="ok"){
      (pr.data||[]).forEach(function(p){ if(p && p.name) EDIT_PRICES.products[p.name] = p; });
      _fillSelect(document.getElementById("e_product"), (pr.data||[]).map(function(p){ return p.name; }), o.product||"");
    }
    if(cr.status==="ok"){
      (cr.data||[]).forEach(function(c){ if(c && c.name) EDIT_PRICES.cities[c.name] = c; });
      _fillSelect(document.getElementById("e_city"), (cr.data||[]).map(function(c){ return c.name; }), o.city||"");
    }
  }catch(e){}
}

// نفس معادلة السيرفر (_price_order): sell×qty + شحن الزبون − discountApplied. السيرفر يعاود يحسب غير
// كي تتبدّل خانة من هادو؛ رجعو كيما كانو → المجموع المخزّن. منتج ولا ولاية ماعادوش: ما نبدّلوش.
function editOrderAutoTotal(){
  var o = ORDERS_BY_ID[EDIT_ORDER_ID];
  if(!o || EDIT_TOTAL_MANUAL) return;
  var totalEl = document.getElementById("e_total");
  var product = document.getElementById("e_product").value, city = document.getElementById("e_city").value;
  var dtype   = document.getElementById("e_delivery").value, status = document.getElementById("e_status").value;
  var qty     = parseInt(document.getElementById("e_qty").value)||0;
  if(product===(o.product||"") && city===(o.city||"") && qty===(parseInt(o.qty)||1) && status===o.status &&
     dtype===(o.deliveryType==="desk" ? "desk" : "home")){
    totalEl.value = EDIT_ORDER_TOTAL0 = EDIT_ORDER_TOTAL_OPEN;
    return;
  }
  var p = EDIT_PRICES.products[product], c = EDIT_PRICES.cities[city];
  if(!p || !c || qty<1) return;
  var ship = dtype==="desk" ? c.deskCust : c.custShip;
  var auto = Math.max(0, Math.round(((parseFloat(p.sell)||0)*qty + (parseFloat(ship)||0) - (parseFloat(o.discountApplied)||0))*100)/100);
  totalEl.value = EDIT_ORDER_TOTAL0 = String(auto);
}

function editOrderTotalTyped(){ EDIT_TOTAL_MANUAL = true; }

async function saveOrderEdit(){
  if(!EDIT_ORDER_ID) return;
  var data = {
    name:         document.getElementById("e_name").value.trim(),
    phone:        document.getElementById("e_phone").value.trim(),
    product:      document.getElementById("e_product").value,
    qty:          parseInt(document.getElementById("e_qty").value)||0,
    city:         document.getElementById("e_city").value,
    deliveryType: document.getElementById("e_delivery").value,
    status:       document.getElementById("e_status").value,
  };
  var totalEl = document.getElementById("e_total");
  if(totalEl.value!==EDIT_ORDER_TOTAL0) data.total = parseFloat(totalEl.value);
  if(!data.name||!data.phone||!data.product||!data.city||data.qty<1){ toast(t("fill_required"),"err"); return; }
  try{
    var r = await apiPost("/editOrder", {orderId:EDIT_ORDER_ID, data:data});
    if(r.status==="ok"){
      if(r.data && r.data.id) _mergeOrders([r.data], true);
      closeModal("editOrderModal");
      filterOrders();
      toast("✅ "+t("order_updated"),"ok");
    } else { toast("❌ "+r.message,"err"); }
  }catch(e){ toast(t("network_error"),"err"); }
}

async function deleteOrder(orderId){
  if(!confirm(t("confirm_delete_order").replace("{id}", orderId))) return;
  try{
    var r = await apiPost("/deleteOrder", {orderId:orderId});
    if(r.status==="ok"){
      _dropOrders([orderId]);
      filterOrders();
      toast("✅ "+t("order_deleted"),"ok");
    } else { toast("❌ "+r.message,"err"); }
  }catch(e){ toast(t("network_error"),"err"); }
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
    toast(t("fill_required"),"err"); return;
  }
  if(!data.deliveryType){
    toast("اختر نوع التوصيل (منزل أو مكتب الاستلام)","err"); return;
  }
  var r = await apiPost("/addOrder", {userId:uid(), data:data}, true);  // التوكن: طلب يدوي من التاجر (حتى فـ Free)
  if(r.status==="ok"){
    toast("✅ "+t("order_added"),"ok");
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

// تصدير الطلبات (آخر 90 يوم) لملف CSV يتحل فـ Excel — التوكن فالهيدر، لهذا fetch + blob
async function exportOrders(){
  try{
    var r = await fetch(API_URL + "/exportOrders", {headers: {"Authorization": "Bearer " + authToken}});
    if(!r.ok){
      var err = {};
      try{ err = await r.json(); }catch(e){}
      toast("❌ " + (err.message || r.status), "err");
      return;
    }
    var blob = await r.blob();
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    // الاسم من الواجهة: هيدر Content-Disposition ما يتقراش من JS كي يكون الـ API فـ origin آخر
    var d = new Date(), pad = function(n){ return (n<10?"0":"")+n; };
    a.download = "orders-" + d.getFullYear() + pad(d.getMonth()+1) + pad(d.getDate()) + ".csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }catch(e){ toast(t("network_error"), "err"); }
}
