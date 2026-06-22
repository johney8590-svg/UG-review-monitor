"""
UG 輿情聲量收集器（免費來源，無金鑰）
------------------------------------------------------------
把儀表板「輿情總覽」從示意資料換成真實資料。來源：
  - Google News RSS：品牌／競品的新聞提及（穩、可靠）
  - Google Trends（pytrends）：搜尋熱度（可靠度中，被限流就跳過）
  - PTT：論壇討論（best-effort 爬蟲，失敗跳過不中斷）

產出 dashboard.json 的：
  brands（綜合聲量熱度榜，含 news/trends/social 真實訊號）、
  alerts（由新聞自動生成的預警）、
  buzzNews（最新新聞列表，給追蹤面板/watchlist 用）、
  buzzMeta（生成時間與各來源筆數，含哪些是估計的標記）。

設計：單一來源失敗一律「跳過不中斷」，逐源錯誤印在 log。
即使全部來源失敗，也回傳結構完整、estimated=True 的資料，不讓前端壞掉。
"""
import json
import re
import html
import datetime
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
KW_CFG = ROOT / "config" / "keywords.json"
DASH = ROOT / "docs" / "data" / "dashboard.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _load_keywords():
    with open(KW_CFG, encoding="utf-8") as f:
        return json.load(f)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-TW,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ───────── Google News RSS ─────────
def _tag(block, tag):
    m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), block, re.S)
    if not m:
        return ""
    t = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S)
    return html.unescape(t).strip()


def fetch_news(query, limit=20):
    """回傳 [{title,url,source,pub(epoch)}]，最新在前。"""
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query)
           + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
    xml = _get(url)
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        b = m.group(1)
        title = _tag(b, "title")
        if not title:
            continue
        out.append({
            "title": title,
            "url": _tag(b, "link"),
            "source": _tag(b, "source"),
            "pub": _parse_rss_date(_tag(b, "pubDate")),
        })
        if len(out) >= limit:
            break
    return out


def _parse_rss_date(s):
    if not s:
        return 0
    # 例：Sat, 21 Jun 2026 03:20:00 GMT
    try:
        from email.utils import parsedate_to_datetime
        return int(parsedate_to_datetime(s).timestamp())
    except Exception:
        return 0


# ───────── Google Trends ─────────
def fetch_trends(terms):
    """回傳 {term: 0-100 近 7 天平均搜尋熱度}；被限流或失敗回 {}。"""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  ⚠️ 未安裝 pytrends，跳過搜尋趨勢")
        return {}
    try:
        py = TrendReq(hl="zh-TW", tz=-480, timeout=(10, 25))
        py.build_payload(terms[:5], timeframe="now 7-d", geo="TW")
        df = py.interest_over_time()
        if df is None or df.empty:
            return {}
        return {t: int(round(df[t].mean())) for t in terms[:5] if t in df.columns}
    except Exception as e:
        print(f"  ⚠️ Google Trends 失敗（常見：被限流），跳過：{e}")
        return {}


# ───────── PTT 論壇（best-effort） ─────────
def fetch_ptt(query, board="Food", limit=15):
    """爬 PTT 指定看板搜尋。失敗回 []。"""
    out = []
    try:
        url = (f"https://www.ptt.cc/bbs/{board}/search?q="
               + urllib.parse.quote(query))
        htmltext = _get(url)
        # 標題列：<div class="title"><a href="/bbs/Food/M.xxx.html">標題</a></div>
        for m in re.finditer(r'<div class="title">\s*<a href="([^"]+)">(.*?)</a>',
                             htmltext, re.S):
            href, title = m.group(1), re.sub(r"<.*?>", "", m.group(2)).strip()
            if not title:
                continue
            out.append({"title": html.unescape(title),
                        "url": "https://www.ptt.cc" + href, "board": board})
            if len(out) >= limit:
                break
    except Exception as e:
        print(f"  ⚠️ PTT 搜尋「{query}」失敗，跳過：{e}")
    return out


# ───────── 組裝 ─────────
def _norm(values):
    """把一組數值正規化到 0-100（相對最大值）。全 0 回全 0。"""
    mx = max(values) if values else 0
    if mx <= 0:
        return [0 for _ in values]
    return [int(round(v / mx * 100)) for v in values]


def collect_buzz():
    kw = _load_keywords()
    brand_terms = kw.get("brand", []) or ["UG"]
    competitors = kw.get("competitor", []) or []
    promo_terms = kw.get("promo", []) or []

    # 用最具代表性的一個詞當每個品牌的查詢主詞
    ug_name = "UG 聯發"
    ug_query = brand_terms[0] if brand_terms else "UG"
    brand_list = [(ug_name, ug_query, True)] + [(c, c, False) for c in competitors]

    print(f"▶ 輿情收集：品牌 {len(brand_list)} 個", flush=True)

    # 1) 新聞
    news_by_brand, news_counts, all_news = {}, [], []
    for name, q, _self in brand_list:
        try:
            items = fetch_news(q, limit=25)
        except Exception as e:
            print(f"  ⚠️ 新聞「{q}」失敗：{e}", flush=True)
            items = []
        news_by_brand[name] = items
        news_counts.append(len(items))
        for it in items[:8]:
            all_news.append({**it, "brand": name})
        print(f"  · {name} 新聞 {len(items)} 則", flush=True)

    # 2) 搜尋趨勢（一次最多 5 詞）
    trend_terms = [q for _n, q, _s in brand_list][:5]
    trends = fetch_trends(trend_terms)
    trends_real = bool(trends)
    print(f"  · Google Trends：{'OK ' + str(trends) if trends_real else '無（限流/失敗）'}", flush=True)

    # 3) PTT 論壇
    ptt_counts, ptt_by_brand = [], {}
    for name, q, _self in brand_list:
        posts = fetch_ptt(q, board="Food", limit=15)
        ptt_by_brand[name] = posts
        ptt_counts.append(len(posts))
    ptt_real = any(ptt_counts)
    print(f"  · PTT：{'OK 共 ' + str(sum(ptt_counts)) + ' 篇' if ptt_real else '無（爬不到/被擋）'}", flush=True)

    # 正規化各訊號
    news_n = _norm(news_counts)
    social_n = _norm(ptt_counts)
    trend_n = [trends.get(q, 0) for _n, q, _s in brand_list]  # 已是 0-100

    brands = []
    for i, (name, q, is_self) in enumerate(brand_list):
        news = news_n[i]
        trends_v = trend_n[i]
        social = social_n[i]
        # 評論訊號：只有自家（UG）有真實 Google 評論，競品無 → 估計
        reviews = 0
        # 真實可得的訊號加權（新聞 40% + 趨勢 35% + 社群 25%）
        score = int(round(news * 0.40 + trends_v * 0.35 + social * 0.25))
        brands.append({
            "name": name, "self": is_self, "score": score, "d": 0,
            "news": news, "trends": trends_v, "reviews": reviews, "social": social,
            "pos": None, "neg": None,                 # 情緒待 AI（ai_report）填，前端顯示「—」
            "estimated": (not trends_real) or (not ptt_real),
        })
    brands.sort(key=lambda b: b["score"], reverse=True)

    # 預警：競品優惠詞出現在近期新聞，或品牌新聞量明顯
    alerts = []
    now_str = datetime.datetime.now().strftime("%m/%d %H:%M")
    for name, items in news_by_brand.items():
        is_self = (name == ug_name)
        for it in items[:15]:
            title = it["title"]
            for p in promo_terms:
                if p in title:
                    lv = "y" if is_self else "r"
                    who = "自家" if is_self else "競品"
                    alerts.append({"lv": lv,
                                   "txt": f"{who}「{name}」新聞出現優惠詞「{p}」：{title}",
                                   "at": now_str})
                    break
        if len(alerts) >= 6:
            break
    if not alerts and all_news:
        top = max(news_by_brand.items(), key=lambda kv: len(kv[1]))
        if top[1]:
            alerts.append({"lv": "g",
                           "txt": f"近期新聞聲量最高：{top[0]}（{len(top[1])} 則）",
                           "at": now_str})

    # 最新新聞列表（給 watchlist / 追蹤）
    all_news.sort(key=lambda x: x.get("pub", 0), reverse=True)
    buzz_news = [{
        "title": n["title"], "url": n["url"], "source": n["source"],
        "brand": n["brand"], "date": _rel_date(n.get("pub", 0)),
    } for n in all_news[:30]]

    # 把最新新聞餵進前端既有的「追蹤清單」區塊（取代示意資料）
    watchlist = [{
        "title": n["title"],
        "url": n["url"],
        "meta": " · ".join([x for x in [n.get("source", ""), n.get("brand", ""), n.get("date", "")] if x]),
    } for n in buzz_news[:6]]

    return {
        "brands": brands,
        "alerts": alerts,
        "watchlist": watchlist,
        "buzzNews": buzz_news,
        "buzzMeta": {
            "generatedAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "news": sum(news_counts), "ptt": sum(ptt_counts),
            "trendsReal": trends_real, "pttReal": ptt_real,
            "note": "新聞與趨勢為真實資料；社群互動(FB/IG/Threads)與情緒為估計，待付費來源或 AI 補。",
        },
    }


def _rel_date(ts):
    if not ts:
        return ""
    days = (datetime.date.today() - datetime.date.fromtimestamp(ts)).days
    if days <= 0:
        return "今天"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def merge_into_dashboard():
    dash = json.loads(DASH.read_text(encoding="utf-8")) if DASH.exists() else {}
    dash.update(collect_buzz())
    DASH.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已更新輿情段 → {DASH}")


if __name__ == "__main__":
    merge_into_dashboard()
