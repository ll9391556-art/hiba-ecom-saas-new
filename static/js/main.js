// =========================================================
// INIT
// =========================================================
applyTheme();
applyLang(currentLang);
restoreSession();

// حماية من bfcache: لو المتصفح رجّع نسخة محفوظة من الصفحة (زر "رجوع")
// بدون ?store= بالرابط، نتأكد السايدبار وMain ظاهرين بالشكل الصحيح
window.addEventListener("pageshow", function(e){
  if(!SHOP_UID){
    var sb = document.getElementById("sidebar"), mn = document.getElementById("main");
    if(sb) sb.style.display = "";
    if(mn) mn.style.display = "";
    document.getElementById("shopApp").style.display = "none";
  }
});
