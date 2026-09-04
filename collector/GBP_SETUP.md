# Google Business Profile API 設定（抓每一則評論，含最新 1 星）

你「擁有」這些門市 → 用官方 Business Profile API 免費抓到**每一則**評論、可排最新、含完整 1 星內文，還能回覆。
Places API 每店只回 5 則且非最新，所以做不到「每天新的 1 星」。設好後系統會**自動優先用它**（`google_reviews.py` 偵測到 `GBP_REFRESH_TOKEN` 就走 GBP）。

> ⏳ **瓶頸是 Google 審核**（步驟 1），要幾天。請「今天先送申請」，其餘審核期間再弄。

---

## 1.（最花時間）申請 Business Profile API 存取權
- 用**管理這些門市 Google 商家的那個 Google 帳號**登入。
- 到 Google Cloud Console 建一個專案（可沿用你 Places 那個）。
- 送出「Business Profile APIs」存取權申請表：
  https://developers.google.com/my-business/content/prereqs （頁面內「Request access」表單）
- 送出後**等 Google 核准**（通常數天）。核准信到了才做得了下面。

## 2. 啟用 API（Cloud Console → API 和服務 → 啟用）
啟用這幾個：
- **Google My Business API**（評論 v4 端點）
- **My Business Account Management API**
- **My Business Business Information API**

## 3. 建 OAuth 用戶端
- 「憑證」→「建立憑證」→「OAuth 用戶端 ID」→ 類型選 **桌面應用程式**（最省事）。
- 記下 **用戶端 ID** 與 **用戶端密鑰**。
- 「OAuth 同意畫面」若要求，把自己的 Google 帳號加進「測試使用者」。

## 4.（一次性）取得 refresh token
最簡單用 **OAuth Playground**：
1. 開 https://developers.google.com/oauthplayground
2. 右上齒輪 → 勾 **Use your own OAuth credentials** → 填步驟 3 的用戶端 ID／密鑰。
3. 左側「Input your own scopes」填：`https://www.googleapis.com/auth/business.manage`
4. 按 **Authorize APIs** → 用你的商家帳號登入允許。
5. 按 **Exchange authorization code for tokens** → 複製 **Refresh token**（`1//...`）。
   - ⚠️ 這串等於長期鑰匙，只貼進 GitHub Secret，別貼進對話或檔案。

## 5. 設 3 個 GitHub Secret
repo → Settings → Secrets and variables → Actions → New secret：

| 名稱 | 值 |
|---|---|
| `GBP_CLIENT_ID` | 步驟 3 的用戶端 ID |
| `GBP_CLIENT_SECRET` | 步驟 3 的用戶端密鑰 |
| `GBP_REFRESH_TOKEN` | 步驟 4 的 refresh token |

## 6. 完成
下次排程（或 admin 頁「立即刷新」）就會自動改用 GBP，`gReviews` 會有每店最多 ~200 則、含**最新 1 星**內文；負評／VOC 也會跟著變完整。

> 註：本程式碼未經實跑（要等你拿到存取權），第一次跑可能需要小除錯（端點/欄位），到時把 Actions 的錯誤訊息貼給我即可。
