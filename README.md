# UG 輿情監測 · Google 商家評論

純靜態儀表板（GitHub Pages）＋ 每日自動抓取（GitHub Actions）。
兩個分頁：**輿情總覽**（競品聲量、SOV、預警、AI 日報）與 **Google 商家**（各門市星等、每日★變化、評論篩選排序）。

## 一次部署（在你自己的電腦，已 `gh auth login`）

```bash
# 1) 填門市白名單（用 Google place_id，不要只靠店名）
cp config/stores.example.json config/stores.json
#    編輯 config/stores.json，填入你的 UG 各店 place_id

# 2) 一鍵部署：git init → 建公開 repo → 設金鑰 → 開 Pages → 跑第一次
bash deploy.sh
```

`deploy.sh` 會：建立公開 repo `ug-review-monitor` 並 push、互動式設定 `OUTSCRAPER_API_KEY`（可選 `ANTHROPIC_API_KEY`，金鑰只進 GitHub Secret、不進任何檔案或指令歷史）、開啟 Pages（main /docs）、給 Actions 寫入權限、觸發第一次抓取，最後印出網址：

```
https://<你的帳號>.github.io/ug-review-monitor/
```

## 架構

```
docs/index.html          靜態儀表板，只讀 docs/data/dashboard.json
docs/data/dashboard.json 資料檔（由排程每天覆寫；現附種子資料可先看畫面）
docs/data/snapshots/     每日快照，用來算「今日★變化」
collector/google_reviews.py  抓 Google 商家評論 + 快照相減 + 負評抽取
collector/ai_report.py       （選用）用 Claude 產生日報/VOC/回覆，寫回 json
config/stores.json       門市白名單（place_id）
config/keywords.json     監測關鍵字（品牌/競品/優惠）
.github/workflows/scrape.yml  每天 09:00 跑，commit 回 repo
```

**金鑰永遠不進前端。** 所有需要金鑰的工作（Outscraper 抓取、Claude 產文）都在 Actions 內跑，結果寫進 `dashboard.json`，前端只負責顯示。

## 接進你「現有」的 collect.py

你已有一套 Outscraper 收集器。把 Google 商家這段接上去最省事的方式：

```python
from collector.google_reviews import collect_google
google = collect_google()        # {"stores":[...], "gReviews":[...]}
dashboard.update(google)         # 併進你既有的 dashboard 物件再寫檔
```

若你的 collect.py 已有 Outscraper 呼叫，可把 `google_reviews.py` 裡的 `fetch_reviews()` 換成你的版本，其餘（快照相減、負評抽取）照用。

## 抓取來源（免金鑰 / 付費，自動二選一）

- **預設：免金鑰爬蟲**。未設 `OUTSCRAPER_API_KEY` 時，排程用 `collector/gmaps_scraper.py`（Playwright 無頭瀏覽器）直接讀 Google 地圖，**不需要任何金鑰**。缺點是直接爬較脆弱（Google 改版／機房 IP 被要求驗證時可能單店暫時抓不到，會跳過不中斷）。
- **選用：Outscraper（付費、最穩）**。只要在 Secrets 設了 `OUTSCRAPER_API_KEY`，`fetch_reviews()` 會自動改走 Outscraper，程式不用改。

## 注意

- 門市比對用 **place_id 白名單**，避免抓到同名或非官方商家。
- 「今日★變化」需要至少兩天快照才有值（第一天為 0）。
- AI 區塊（日報/週報/VOC/GEO）若沒設 `ANTHROPIC_API_KEY`，前端會顯示「由排程產生」字樣，其餘功能照常。
