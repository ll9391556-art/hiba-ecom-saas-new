// =========================================================
// THEME TOGGLE — وضع النهار / الليل
// =========================================================
var DARK_MODE = localStorage.getItem("of_theme") !== "light";

function applyTheme(){
  var pill = document.getElementById("themePill");
  var dot  = document.getElementById("themeDot");
  var lbl  = document.getElementById("themeLabel");
  if(DARK_MODE){
    document.documentElement.style.removeProperty("--bg");
    document.documentElement.style.removeProperty("--sidebar");
    document.documentElement.style.removeProperty("--card");
    document.documentElement.style.removeProperty("--card2");
    document.documentElement.style.removeProperty("--text");
    document.documentElement.style.removeProperty("--muted");
    document.documentElement.style.removeProperty("--border");
    if(pill){ pill.style.background="rgba(255,255,255,.12)"; }
    if(dot){  dot.style.transform="translateX(0)"; }
    if(lbl){  lbl.textContent="☀️ Mode Clair"; }
  } else {
    document.documentElement.style.setProperty("--bg",      "#f0f4f8");
    document.documentElement.style.setProperty("--sidebar", "#ffffff");
    document.documentElement.style.setProperty("--card",    "#ffffff");
    document.documentElement.style.setProperty("--card2",   "#f8fafc");
    document.documentElement.style.setProperty("--text",    "#1e293b");
    document.documentElement.style.setProperty("--muted",   "#64748b");
    document.documentElement.style.setProperty("--border",  "rgba(0,0,0,0.09)");
    if(pill){ pill.style.background="#2563eb"; }
    if(dot){  dot.style.transform="translateX(15px)"; }
    if(lbl){  lbl.textContent="🌙 Mode Sombre"; }
  }
  var activeSec = document.querySelector(".section.active");
  if(activeSec && activeSec.id==="sec_dashboard" && currentUser) loadDashboard();
}

function toggleTheme(){
  DARK_MODE = !DARK_MODE;
  localStorage.setItem("of_theme", DARK_MODE ? "dark" : "light");
  applyTheme();
}

