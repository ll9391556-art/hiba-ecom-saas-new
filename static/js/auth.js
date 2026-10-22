// =========================================================
// LOGIN
// =========================================================
async function doLogin(){
  var u = document.getElementById("loginUser").value.trim();
  var p = document.getElementById("loginPass").value.trim();
  if(!u||!p){ showLoginErr(t("fill_all")); return; }
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
      showLoginErr(r.message||t("bad_credentials"));
    }
  }catch(e){ showLoginErr(t("server_error")); }
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

