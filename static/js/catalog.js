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
        var stCls = {InStock:"bs","In Stock":"bs","Low Stock":"bn",LowStock:"bn","Out of Stock":"br",OutOfStock:"br"}[p.stat||""]||"bp";
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
          '<td><span class="badge '+stCls+'">'+esc(stockLabel(p.stat||"?"))+'</span></td>'+
          '<td><button class="btn-danger" data-name="'+esc(p.name)+'" data-on-click="deleteProduct(this.dataset.name)"><i class="bi bi-trash"></i></button></td>'+
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
  if(!data.name){ toast(t("enter_product_name"),"err"); return; }
  var r = await apiPost("/addProduct", {data:data});
  if(r.status==="ok"){
    toast("✅ "+t("product_added"),"ok");
    currentProductImages = [];
    renderProductImageThumbs();
    closeModal("addProductModal");
    loadProducts();
  } else { toast("❌ "+r.message,"err"); }
}

async function deleteProduct(name){
  if(!confirm(t("confirm_delete").replace("{name}", name))) return;
  var r = await apiPost("/deleteProduct", {data:{name:name}});
  if(r.status==="ok"){ toast("✅ "+t("deleted"),"ok"); loadProducts(); }
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
    var typeCls = {Good:"bs",Bad:"br",Neutral:"bn"}[c.type]||"bp";
    return '<tr>'+
      '<td><strong>'+esc(c.name||"—")+'</strong></td>'+
      '<td>'+esc(c.phone||"—")+'</td>'+
      '<td>'+esc(c.city||"—")+'</td>'+
      '<td>'+esc(c.totalOrders||0)+'</td>'+
      '<td style="color:var(--green)">'+esc(c.stats&&c.stats.confirmed||0)+'</td>'+
      '<td style="color:var(--blue)">'+esc(c.stats&&c.stats.delivered||0)+'</td>'+
      '<td style="color:var(--red)">'+esc(c.stats&&c.stats.refused||0)+'</td>'+
      '<td><span class="badge '+typeCls+'">'+esc(custLabel(c.type||"?"))+'</span></td>'+
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
          '<td><button class="btn-danger" data-name="'+esc(c.name)+'" data-on-click="deleteCity(this.dataset.name)"><i class="bi bi-trash"></i></button></td>'+
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
  if(!data.name){ toast(t("enter_city_name"),"err"); return; }
  var r = await apiPost("/addCity", {data:data});
  if(r.status==="ok"){ toast("✅ "+t("city_added"),"ok"); closeModal("addCityModal"); loadCities(); }
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

