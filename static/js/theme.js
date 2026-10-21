// =========================================================
// THEME — الوضع الفاتح ديما (Design D1: ممنوع الخلفيات الداكنة)
// الألوان كاملين فـ /static/css/tokens.css. الدوال باقيين لأن main.js و shop-main.js
// يناديو applyTheme()، و dashboard.js يقرا DARK_MODE لألوان المخطط.
// =========================================================
var DARK_MODE = false;

function applyTheme(){
  // كانت نسخ قديمة تكتب الألوان inline على <html>؛ نمسحوها باش tokens.css يحكم
  ["--bg","--sidebar","--card","--card2","--text","--muted","--border"].forEach(function(v){
    document.documentElement.style.removeProperty(v);
  });
}

function toggleTheme(){
  applyTheme();
}
