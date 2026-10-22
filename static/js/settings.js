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
      tbl.innerHTML = '<tr><td colspan="5" class="empty-state">'+esc(r.message||t("error"))+'</td></tr>';
    }
  }catch(e){ tbl.innerHTML = '<tr><td colspan="5" class="empty-state">'+t("error")+'</td></tr>'; }
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
      ? '<span class="badge bs">'+t("active")+'</span>'
      : '<span class="badge br">'+t("inactive")+'</span>';
    return '<tr>'+
      '<td><strong>'+esc(m.username)+'</strong></td>'+
      '<td>'+esc(m.name||m.username)+'</td>'+
      '<td style="white-space:normal;max-width:280px">'+permsHtml+'</td>'+
      '<td>'+statusBadge+'</td>'+
      '<td data-user="'+esc(m.username)+'"><div style="display:flex;gap:6px">'+
        '<button class="btn-outline btn-sm" data-on-click="openEditMemberModal(this.closest(\'td\').dataset.user)"><i class="bi bi-pencil"></i></button>'+
        '<button class="btn-danger" data-on-click="deleteTeamMember(this.closest(\'td\').dataset.user)"><i class="bi bi-trash"></i></button>'+
      '</div></td>'+
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
  }catch(e){ toast(t("network_error"),"err"); }
}

async function deleteTeamMember(username){
  if(!confirm(t("confirm_delete_member"))) return;
  try{
    var r = await apiPost("/team/deleteMember", {username:username});
    if(r.status==="ok"){ toast("✅ "+t("delete"),"ok"); loadTeam(); }
    else toast("❌ "+r.message,"err");
  }catch(e){ toast(t("network_error"),"err"); }
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
      if(!logs.length){ div.innerHTML='<div style="text-align:center;padding:20px;color:var(--muted)">'+esc(t("no_logs"))+'</div>'; return; }
      div.innerHTML = logs.map(function(l){
        var date     = l.date     || (l.timestamp ? new Date(l.timestamp*1000).toLocaleString("fr-DZ") : "—");
        var platform = l.platform || "FB";
        var userMsg  = l.user_message || l.user || "";
        var botReply = l.bot_reply   || l.bot  || "";
        var sender   = l.sender_id   ? '<span style="font-size:9px;color:var(--muted);margin-left:6px">'+esc(l.sender_id.substring(0,8))+'...</span>' : "";
        return '<div style="border-bottom:1px solid var(--border);padding:10px 0">'+
          '<div style="color:var(--muted);font-size:10px;margin-bottom:4px">'+esc(date)+' • '+esc(platform)+sender+'</div>'+
          (userMsg  ? '<div style="background:rgba(37,99,235,.08);border-radius:8px;padding:6px 10px;margin-bottom:4px;font-size:12px"><span style="color:var(--muted);font-size:10px">👤 '+esc(t("log_client"))+'</span><br>'+esc(userMsg.substring(0,200))+'</div>' : '')+
          (botReply ? '<div style="background:rgba(16,185,129,.08);border-radius:8px;padding:6px 10px;font-size:12px"><span style="color:var(--muted);font-size:10px">🤖 '+esc(t("log_bot"))+'</span><br>'+esc(botReply.substring(0,300))+'</div>' : '')+
        '</div>';
      }).join("");
    }
  }catch(e){ div.innerHTML='<div style="color:var(--red);padding:10px">'+esc(t("error")+": "+e.message)+'</div>'; }
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
      el.innerHTML = '<span style="color:var(--green)"><i class="bi bi-check-circle"></i> '+t("connected")+'</span> — '+esc(d.updated_at||"");
    } else {
      el.innerHTML = '<span style="color:var(--muted)"><i class="bi bi-x-circle"></i> '+t("not_connected")+'</span>';
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
      toast("✅ "+t("fb_connected_ok"),"ok");
      window.removeEventListener("message", handler);
      reloadFromServer();
    }
    if(ev.data.type==="FB_AUTH_ERROR"){
      toast("❌ "+t("error")+": "+String(ev.data.message||""),"err");
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
  if(!confirm(t("confirm_disconnect_fb"))) return;
  await fetch(FB_BACKEND+"/fb-disconnect", {
    method:"POST",
    headers: authToken ? {"Authorization":"Bearer "+authToken} : {}
  });
  toast("✅ "+t("disconnected"),"ok");
  loadSettings();
}

async function checkFbStatus(){
  var el = document.getElementById("fbConnectStatus");
  var pl = document.getElementById("fbPagesList");
  var pc = document.getElementById("fbPagesContent");
  if(!el) return;
  el.textContent = "⏳ "+t("checking");
  try{
    var r = await fetch(FB_BACKEND+"/fb-status", {
      headers: authToken ? {"Authorization":"Bearer "+authToken} : {}
    });
    var d = await r.json();
    if(d.connected){
      el.innerHTML = '<span style="color:var(--green)">✅ '+t("connected")+' — '+esc(d.updated_at||"—")+'</span>';
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
      el.innerHTML = '<span style="color:var(--red)">❌ '+t("not_connected")+'</span>';
      if(pl) pl.style.display="none";
    }
  }catch(e){
    if(el) el.innerHTML = '<span style="color:var(--muted)">⚠️ '+t("server_error")+'</span>';
  }
}
 

