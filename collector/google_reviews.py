"""
UG 門市 Google 商家評論抓取（Outscraper）
------------------------------------------------
產出 dashboard.json 的 stores / gReviews 兩段，並用「每日快照相減」算出今日★變化。

設計重點：
- 門市用「白名單 place_id」比對，不靠店名（避免誤抓同名或他人商家）。
- 金鑰只從環境變數讀（GitHub Action 的 OUTSCRAPER_API_KEY Secret），不寫進檔案。
- 每天存一份快照到 docs/data/snapshots/<日期>.json，隔天相減得到 dRating / 新增評論數。

整合方式：在你現有的 collect.py 結尾呼叫 collect_google()，把回傳的兩段塞進 dashboard.json。
"""
import os, json, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "docs" / "data" / "snapshots"
STORES_CFG = ROOT / "config" / "stores.json"
NEG_THRESHOLD = 2  # ★ <= 2 視為負評


def _load_stores():
    """讀白名單門市：[{name, place_id}]"""
    with open(STORES_CFG, encoding="utf-8") as f:
        return json.load(f)["stores"]


def _fetch_outscraper(query, limit):
    """付費路徑：有 OUTSCRAPER_API_KEY 時走 Outscraper（最穩、可抓多則）。"""
    api_key = os.environ["OUTSCRAPER_API_KEY"]
    from outscraper import ApiClient  # pip install outscraper
    client = ApiClient(api_key=api_key)
    res = client.google_maps_reviews([query], reviews_limit=limit, language="zh-TW")
    if not res:
        return None, 0, [], None
    place = res[0]
    reviews = []
    for r in place.get("reviews_data", []) or []:
        reviews.append({
            "stars": int(r.get("review_rating") or 0),
            "text": (r.get("review_text") or "").strip(),
            "author": r.get("author_title") or "匿名",
            "ts": int(r.get("review_timestamp") or 0),
        })
    return place.get("rating"), place.get("reviews"), reviews, place.get("place_id") or query


def fetch_reviews(query, limit=50):
    """
    抓單一商家評論。query 可為 Google place_id、店名或地址。
    回傳 (rating, reviews_count, [reviews], resolved_place_id)。
    來源自動切換：
      - 有設 OUTSCRAPER_API_KEY → 走 Outscraper（付費、最穩）
      - 沒設                    → 走免費無金鑰的 Playwright 爬蟲（gmaps_scraper）
    """
    if os.environ.get("OUTSCRAPER_API_KEY"):
        return _fetch_outscraper(query, limit)
    try:
        from gmaps_scraper import scrape_place        # 以 script 方式跑（collector/ 在 sys.path）
    except ImportError:
        from collector.gmaps_scraper import scrape_place
    return scrape_place(query, limit=min(limit, 20))


def _today():
    return datetime.date.today().isoformat()


def _read_snapshot(day):
    p = SNAP_DIR / f"{day}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _write_snapshot(day, data):
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"{day}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _rel_date(ts):
    if not ts:
        return ""
    days = (datetime.date.today() - datetime.date.fromtimestamp(ts)).days
    return {0: "今天", 1: "昨天"}.get(days, f"{days} 天前")


def collect_google():
    today = _today()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    prev = _read_snapshot(yesterday)

    stores_out, reviews_out, snapshot = [], [], {}

    all_stores = _load_stores()
    for i, s in enumerate(all_stores, 1):
        name = s["name"]
        query = s.get("place_id") or s.get("query") or name  # place_id 最精準，其次搜尋詞
        print(f"[{i}/{len(all_stores)}] 抓取 {name} …", flush=True)
        try:
            rating, count, reviews, pid = fetch_reviews(query)
        except Exception as e:
            print(f"    ⚠️ {name} 失敗，跳過：{e}", flush=True)
            continue
        if rating is None:
            print(f"    ⚠️ {name} 查無結果，跳過", flush=True)
            continue
        key = query  # 用穩定字串當快照 key，確保跨天相減一致（爬蟲的 place_id 可能不穩）
        print(f"    ✓ {rating}★ / {count} 則，抓到 {len(reviews)} 則評論", flush=True)

        snapshot[key] = {"rating": rating, "reviews": count}

        # 今日★變化 / 新增評論：與昨日快照相減
        prev_s = prev.get(key, {})
        d_rating = round(rating - prev_s.get("rating", rating), 2)
        new_today = max(count - prev_s.get("reviews", count), 0)
        neg_count = sum(1 for r in reviews if 0 < r["stars"] <= NEG_THRESHOLD)

        stores_out.append({
            "name": name, "rating": rating, "reviews": count,
            "dRating": d_rating, "newToday": new_today, "neg": neg_count,
        })

        for r in reviews:
            if not r["text"]:
                continue
            reviews_out.append({
                "store": name, "stars": r["stars"], "date": _rel_date(r["ts"]),
                "author": r["author"], "text": r["text"], "ts": r["ts"],
            })

    _write_snapshot(today, snapshot)

    # 評論預設最新在前
    reviews_out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return {"stores": stores_out, "gReviews": reviews_out}


def merge_into_dashboard():
    """獨立執行：把 google 段併進現有 dashboard.json。"""
    dash_path = ROOT / "docs" / "data" / "dashboard.json"
    dash = json.loads(dash_path.read_text(encoding="utf-8")) if dash_path.exists() else {}
    dash.update(collect_google())
    dash["today"] = datetime.datetime.now().strftime("%Y年%m月%d日")
    dash_path.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新 {dash_path}")


if __name__ == "__main__":
    merge_into_dashboard()
