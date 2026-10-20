// =========================================================
// API  (يرفق تلقائياً Authorization: Bearer <token> على كل طلب محمي)
// =========================================================
async function apiGet(path, params, authed){
  if(authed === undefined) authed = true;
  var url = API_URL + path;
  if(params){
    var q = new URLSearchParams(params);
    url += "?" + q.toString();
  }
  var headers = {};
  if(authed && authToken) headers["Authorization"] = "Bearer " + authToken;
  var r = await fetch(url, {headers: headers});
  return r.json();
}

async function apiPost(path, body, authed){
  if(authed === undefined) authed = true;
  var headers = {"Content-Type":"application/json"};
  if(authed && authToken) headers["Authorization"] = "Bearer " + authToken;
  var r = await fetch(API_URL + path, {
    method:"POST", headers: headers,
    body: JSON.stringify(body)
  });
  return r.json();
}

function uid(){ return currentUser ? (currentUser.User_ID||currentUser.user_id||"") : ""; }
function uname(){ return currentUser ? (currentUser.Username||currentUser.username||"") : ""; }

