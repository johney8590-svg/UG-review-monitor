# UG 門市管理後端（GAS）

`admin.html` 的寫入代理。前端把門市清單 POST 給這支 GAS，GAS 持有 GitHub Token，
commit 回 `config/stores.json`。**Token 永不進前端、不進 repo。**

```
docs/admin.html  ──POST(JSON, 含通關密語)──▶  GAS doPost  ──GitHub Contents API──▶  config/stores.json
```

## 一、建立 GitHub Token（fine-grained，最小權限）

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
2. **Repository access**：Only select repositories → 只勾 `UG-review-monitor`
3. **Permissions → Repository permissions → Contents：Read and write**（其餘維持 No access）
4. 產生後複製 token（`github_pat_...`）。**只在下一步貼進 GAS，別貼到任何檔案或聊天視窗。**

## 二、部署 GAS

### 方式 A：clasp（推薦，和你其他後端一致）

```bash
cd backend/store-admin
clasp create --type webapp --title "UG 門市管理後端"   # 第一次；會產生 .clasp.json
clasp push
```
> 若已建過專案，把現有 scriptId 填進 `.clasp.json`（可用 `.clasp.json.example` 複製）後直接 `clasp push`。

### 方式 B：手動

1. https://script.google.com → 新增專案
2. 把 `Code.gs` 內容貼進去；專案設定打開「顯示 appsscript.json」後貼入 `appsscript.json`

## 三、設定指令碼屬性（金鑰存放處）

專案設定（齒輪）→ **指令碼屬性** → 新增兩個：

| 屬性名 | 值 |
|--------|-----|
| `GH_TOKEN` | 第一步的 GitHub fine-grained PAT |
| `ADMIN_SECRET` | 自訂通關密語（admin 頁要輸入同一組） |

## 四、部署為網頁應用程式

部署 → 新增部署 → 類型「網頁應用程式」：
- 執行身分：**我**
- 具有存取權的人：**任何人**

第一次部署會跳 OAuth 授權（因為要 `UrlFetchApp` 外連 GitHub），按允許。
複製 **網頁應用程式 URL（/exec 結尾）**。

## 五、啟用

打開 `https://johney8590-svg.github.io/UG-review-monitor/admin.html`，
在「連線設定」填入上一步的 `/exec` URL 與通關密語 → 載入門市 → 增刪 → 儲存到 GitHub。

## 安全備註
- 通關密語為內部工具等級驗證（非企業級身分），交接資訊部門時需註明。
- Token 外洩時：到 GitHub 撤銷該 fine-grained token 再重發、更新 `GH_TOKEN` 即可，不影響線上服務。
- 每次儲存都是一次 commit，有版本歷史可回溯。
