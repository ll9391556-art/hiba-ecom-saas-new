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

