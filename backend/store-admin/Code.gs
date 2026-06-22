/**
 * UG 門市管理 — GAS 後端
 * ------------------------------------------------------------------
 * 角色：admin.html 的寫入代理。持有 GitHub Token，把門市白名單
 *       commit 回 repo 的 config/stores.json。Token 永不進前端。
 *
 * 需在「專案設定 → 指令碼屬性」設定兩個值：
 *   GH_TOKEN     : GitHub fine-grained PAT（只授權本 repo 的 Contents 讀寫）
 *   ADMIN_SECRET : 通關密語（admin.html 連線時要輸入同一組）
 *
 * 部署：以網頁應用程式部署，執行身分=我，存取權=任何人。
 */

var REPO      = 'johney8590-svg/UG-review-monitor';
var FILE_PATH = 'config/stores.json';
var BRANCH    = 'main';

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    var props = PropertiesService.getScriptProperties();
    var ADMIN_SECRET = props.getProperty('ADMIN_SECRET');
    var GH_TOKEN     = props.getProperty('GH_TOKEN');

    if (!ADMIN_SECRET) {
      return json({ ok: false, error: '後端未設定 ADMIN_SECRET（請見指令碼屬性）' });
    }
    if (body.secret !== ADMIN_SECRET) {
      return json({ ok: false, error: '通關密語錯誤' });
    }

    // 團隊貼文/評論追蹤（只需密語，不需 GitHub Token；狀態存私有 Google Sheet）
    if (body.action === 'track_list') {
      return json({ ok: true, items: trackList_() });
    }
    if (body.action === 'track_set') {
      return json(trackSet_(body.item || {}));
    }

    // 以下動作需要 GitHub Token
    if (!GH_TOKEN) {
      return json({ ok: false, error: '後端未設定 GH_TOKEN（門市管理／立即刷新需要；追蹤功能不需要）' });
    }

    // 立即刷新：觸發 GitHub Actions 排程重抓 Google 評論（PAT 需含 Actions:write）
    if (body.action === 'refresh') {
      return json(ghDispatch_(GH_TOKEN));
    }

    if (body.action === 'list') {
      var file = ghGet_(GH_TOKEN);
      return json({ ok: true, note: file.data['_說明'] || '', stores: file.data.stores || [] });
    }

    if (body.action === 'save') {
      if (!Array.isArray(body.stores)) return json({ ok: false, error: 'stores 格式錯誤' });
      var clean = [];
      var seen = {};
      for (var i = 0; i < body.stores.length; i++) {
        var s = body.stores[i] || {};
        var name  = String(s.name  || '').trim();
        var query = String(s.query || '').trim();
        if (!name || !query) continue;
        if (seen[name]) continue;          // 去重（同名只留一筆）
        seen[name] = 1;
        clean.push({ name: name, query: query });
      }
      if (!clean.length) return json({ ok: false, error: '至少要有一筆有效門市' });

      var cur = ghGet_(GH_TOKEN);
      var newData = {
        '_說明': cur.data['_說明'] || '門市白名單。query 可填 Google place_id 或「店名＋地址」搜尋詞。',
        stores: clean
      };
      ghPut_(GH_TOKEN, newData, cur.sha, '門市管理頁更新 stores.json（' + clean.length + ' 間）');
      return json({ ok: true, count: clean.length });
    }

    return json({ ok: false, error: '未知 action' });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  }
}

function doGet() {
  return json({ ok: true, msg: 'UG 門市管理後端運作中，請改用 POST。' });
}

/* ---------- GitHub Contents API ---------- */

function ghApi_(token, method, payload) {
  var url = 'https://api.github.com/repos/' + REPO + '/contents/' + FILE_PATH
          + (method === 'get' ? ('?ref=' + BRANCH) : '');
  var opt = {
    method: method,
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'ug-store-admin'
    },
    muteHttpExceptions: true
  };
  if (payload) { opt.contentType = 'application/json'; opt.payload = JSON.stringify(payload); }
  var res  = UrlFetchApp.fetch(url, opt);
  var code = res.getResponseCode();
  var txt  = res.getContentText();
  if (code < 200 || code >= 300) throw new Error('GitHub API ' + code + '：' + txt);
  return JSON.parse(txt);
}

function ghGet_(token) {
  var r = ghApi_(token, 'get');
  var content = Utilities.newBlob(Utilities.base64Decode(String(r.content).replace(/\s/g, '')))
                         .getDataAsString('UTF-8');
  return { sha: r.sha, data: JSON.parse(content) };
}

function ghPut_(token, dataObj, sha, message) {
  var bytes   = Utilities.newBlob(JSON.stringify(dataObj, null, 2)).getBytes();
  var content = Utilities.base64Encode(bytes);
  return ghApi_(token, 'put', { message: message, content: content, sha: sha, branch: BRANCH });
}

// 觸發 scrape.yml 排程（workflow_dispatch）；成功回 204。需 token 有 Actions:write。
function ghDispatch_(token) {
  var url = 'https://api.github.com/repos/' + REPO + '/actions/workflows/scrape.yml/dispatches';
  var res = UrlFetchApp.fetch(url, {
    method: 'post',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'ug-store-admin'
    },
    contentType: 'application/json',
    payload: JSON.stringify({ ref: BRANCH }),
    muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  if (code === 204) return { ok: true, dispatched: true };
  if (code === 403) return { ok: false, error: 'Token 缺 Actions:write 權限（請在 fine-grained PAT 加上）' };
  return { ok: false, error: 'GitHub dispatch ' + code + '：' + res.getContentText().slice(0, 200) };
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}

/* ---------- 團隊追蹤：私有 Google Sheet 當資料表 ---------- */
// 自動建立一份私有試算表（ID 存指令碼屬性 TRACK_SHEET_ID），分頁 tracking。
// 欄位：key | status | tags | assignee | note | updatedAt | updatedBy
var TRACK_HEAD = ['key', 'status', 'tags', 'assignee', 'note', 'updatedAt', 'updatedBy'];

function trackSheet_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('TRACK_SHEET_ID');
  var ss = null;
  if (id) { try { ss = SpreadsheetApp.openById(id); } catch (e) { ss = null; } }
  if (!ss) {
    ss = SpreadsheetApp.create('UG 追蹤狀態（勿刪）');
    props.setProperty('TRACK_SHEET_ID', ss.getId());
  }
  var sh = ss.getSheetByName('tracking');
  if (!sh) {
    sh = ss.insertSheet('tracking');
    sh.appendRow(TRACK_HEAD);
  }
  return sh;
}

function trackList_() {
  var sh = trackSheet_();
  var values = sh.getDataRange().getValues();
  var out = [];
  for (var i = 1; i < values.length; i++) {
    var r = values[i];
    if (!r[0]) continue;
    out.push({
      key: String(r[0]), status: r[1] || '', tags: r[2] || '',
      assignee: r[3] || '', note: r[4] || '',
      updatedAt: r[5] || '', updatedBy: r[6] || ''
    });
  }
  return out;
}

function trackSet_(item) {
  var key = String(item.key || '').trim();
  if (!key) return { ok: false, error: '缺 key' };
  var sh = trackSheet_();
  var now = Utilities.formatDate(new Date(), 'Asia/Taipei', 'yyyy-MM-dd HH:mm');
  var row = [key, String(item.status || ''), String(item.tags || ''),
             String(item.assignee || ''), String(item.note || ''), now,
             String(item.updatedBy || '')];
  var values = sh.getDataRange().getValues();
  for (var i = 1; i < values.length; i++) {
    if (String(values[i][0]) === key) {
      sh.getRange(i + 1, 1, 1, TRACK_HEAD.length).setValues([row]);
      return { ok: true, updated: true, updatedAt: now };
    }
  }
  sh.appendRow(row);
  return { ok: true, created: true, updatedAt: now };
}
