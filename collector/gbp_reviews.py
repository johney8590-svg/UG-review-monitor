"""
Google Business Profile API 評論收集器
------------------------------------------------------------
你「擁有」這些門市 → 用官方 Business Profile API 免費抓到【每一則】評論、
可排最新、含完整內文與 1 星負評（Places API 每店只給 5 則且非最新，做不到）。

需 GitHub Secret（都存 GitHub，不進前端）：
  GBP_CLIENT_ID      OAuth 用戶端 ID
  GBP_CLIENT_SECRET  OAuth 用戶端密鑰
  GBP_REFRESH_TOKEN  一次性 OAuth 授權取得的 refresh token（access_type=offline）

並須先向 Google 申請「Business Profile APIs」存取權（審核制）。

回傳 collect_gbp() -> {"stores":[...], "gReviews":[...]}，格式與 google_reviews 一致，
供 merge 直接取代 Places 版。單一門市失敗跳過不中斷。
"""
import os
import json
import datetime
import urllib.parse
import urllib.request
import urllib.error

TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCT_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
LOC_URL = "https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations"
REVIEWS_URL = "https://mybusiness.googleapis.com/v4/{account}/{location}/reviews"

STAR = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
NEG_THRESHOLD = 2


def _http(url, headers=None, data=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: "
                           f"{e.read().decode('utf-8')[:300]}")


def _access_token():
    body = urllib.parse.urlencode({
        "client_id": os.environ["GBP_CLIENT_ID"],
        "client_secret": os.environ["GBP_CLIENT_SECRET"],
        "refresh_token": os.environ["GBP_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    r = _http(TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body, "POST")
    return r["access_token"]


def _iso_ts(s):
    if not s:
        return 0
    try:
        return int(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _rel(ts):
    if not ts:
        return ""
    days = (datetime.date.today() - datetime.date.fromtimestamp(ts)).days
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def _list_locations(acct_name, H):
    locs, page = [], None
    while True:
        url = LOC_URL.format(account=acct_name) + "?readMask=name,title&pageSize=100"
        if page:
            url += "&pageToken=" + page
        resp = _http(url, H)
        locs += resp.get("locations", [])
        page = resp.get("nextPageToken")
        if not page:
            break
    return locs


def _fetch_reviews(acct_name, loc_name, H, max_pages=4):
    """抓單一門市評論（排最新，最多 max_pages*50 則）。回 (avgRating, total, [reviews])。"""
    reviews, page = [], None
    avg, total = None, 0
    for _ in range(max_pages):
        url = (REVIEWS_URL.format(account=acct_name, location=loc_name)
               + "?" + urllib.parse.urlencode({"orderBy": "updateTime desc", "pageSize": 50}))
        if page:
            url += "&pageToken=" + page
        resp = _http(url, H)
        avg = resp.get("averageRating", avg)
        total = resp.get("totalReviewCount", total)
        for rv in resp.get("reviews", []):
            ts = _iso_ts(rv.get("updateTime") or rv.get("createTime"))
            reviews.append({
                "stars": STAR.get(rv.get("starRating", ""), 0),
                "text": (rv.get("comment") or "").strip(),
                "author": (rv.get("reviewer") or {}).get("displayName") or "匿名",
                "ts": ts,
            })
        page = resp.get("nextPageToken")
        if not page:
            break
    return avg, total, reviews


def collect_gbp():
    token = _access_token()
    H = {"Authorization": "Bearer " + token}
    accounts = _http(ACCT_URL, H).get("accounts", [])
    if not accounts:
        print("  ⚠️ 找不到 Business Profile 帳號")
        return {"stores": [], "gReviews": []}

    stores_out, reviews_out = [], []
    for acct in accounts:
        acct_name = acct["name"]                 # accounts/123
        try:
            locs = _list_locations(acct_name, H)
        except Exception as e:
            print(f"  ⚠️ 列門市失敗（{acct_name}）：{e}", flush=True)
            continue
        print(f"▶ GBP 帳號 {acct_name}：{len(locs)} 家門市", flush=True)

        for loc in locs:
            loc_name = loc["name"]               # locations/456
            title = loc.get("title", loc_name)
            try:
                avg, total, reviews = _fetch_reviews(acct_name, loc_name, H)
            except Exception as e:
                print(f"  ⚠️ {title} 評論失敗，跳過：{e}", flush=True)
                continue
            neg = sum(1 for r in reviews if 0 < r["stars"] <= NEG_THRESHOLD)
            new_today = sum(1 for r in reviews if _rel(r["ts"]) == "今天")
            stores_out.append({
                "name": title, "rating": round(avg, 1) if avg else None,
                "reviews": total, "dRating": 0, "newToday": new_today, "neg": neg,
            })
            for r in reviews:
                if not r["text"]:
                    continue
                reviews_out.append({
                    "store": title, "stars": r["stars"], "date": _rel(r["ts"]),
                    "author": r["author"], "text": r["text"], "ts": r["ts"],
                })
            print(f"    ✓ {title}：{avg}★ / {total} 則，抓到 {len(reviews)} 則（今日新 {new_today}）", flush=True)

    reviews_out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return {"stores": stores_out, "gReviews": reviews_out}


if __name__ == "__main__":
    import pathlib
    dash_path = pathlib.Path(__file__).resolve().parents[1] / "docs" / "data" / "dashboard.json"
    dash = json.loads(dash_path.read_text(encoding="utf-8")) if dash_path.exists() else {}
    dash.update(collect_gbp())
    dash["today"] = datetime.datetime.now().strftime("%Y年%m月%d日")
    dash_path.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已更新 dashboard.json（GBP 評論）")
