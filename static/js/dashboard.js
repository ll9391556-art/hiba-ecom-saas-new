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
      PLAN_FEATURES = r.data.features || {};
      PLAN_USAGE = r.data.usage || {};
      USER_SOURCE = r.data.source || "local";
      LIFETIME_SLOTS_LEFT = r.data.lifetimeSlotsLeft;
      EARLY_SLOTS_LEFT = r.data.earlySlotsLeft;
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

// الميزات جاية من PLANS فالسيرفر (features فـ /api/getUserPlan) — ما كاينش نسخة ثانية هنا
function planHas(feature){
  return !!(PLAN_FEATURES && PLAN_FEATURES[feature]);
}

function highlightCurrentPlan(){
  ["free","starter","pro","business","early","lifetime"].forEach(function(p){
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
  var early = document.getElementById("earlySlotsBadge");
  if(early){
    var hasSlots = EARLY_SLOTS_LEFT!==null && EARLY_SLOTS_LEFT!==undefined;
    early.style.display = hasSlots ? "inline-block" : "none";
    if(hasSlots) early.textContent = "🔥 "+EARLY_SLOTS_LEFT+" "+t("early_slots_left");
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

