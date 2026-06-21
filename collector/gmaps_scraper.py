"""
免費 · 無金鑰的 Google 地圖評論爬蟲（Playwright 無頭瀏覽器）
------------------------------------------------------------
給 google_reviews.py 當「沒有 OUTSCRAPER_API_KEY 時」的後備抓取器。
不需要任何 API 金鑰，在 GitHub Actions 內跑 chromium 直接讀 Google 地圖。

回傳格式與 Outscraper 版一致：
    scrape_place(query) -> (rating, reviews_count, [reviews], place_id)
    reviews 每筆：{stars, text, author, ts(epoch)}

⚠️ 注意：直接爬 Google 地圖本質上較脆弱——版面改版、機房 IP 被要求驗證、
   單店暫時抓不到都可能發生。本模組對單店失敗採「跳過不中斷」，
   讓其餘門市照常更新。逐店錯誤會印在 log。
"""
import re
import time
import datetime
import urllib.parse

_CN_NUM = {"一": 1, "兩": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_int(s):
    """把『3』或中文『三』『兩』轉成數字；抓不到回 1。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    return 1


def _rel_to_ts(text):
    """把 Google 的相對時間（中文）換成大約的 epoch 秒。抓不到回 0。"""
    if not text:
        return 0
    now = datetime.datetime.now()
    t = text.strip()
    if "剛剛" in t or "秒" in t:
        return int(now.timestamp())
    m = re.search(r"(\d+|[一兩二三四五六七八九十]+)\s*(分鐘|小時|天|週|周|個月|月|年)", t)
    if not m:
        if "昨天" in t:
            return int((now - datetime.timedelta(days=1)).timestamp())
        return 0
    n = _cn_int(m.group(1))
    unit = m.group(2)
    delta = {
        "分鐘": datetime.timedelta(minutes=n),
        "小時": datetime.timedelta(hours=n),
        "天": datetime.timedelta(days=n),
        "週": datetime.timedelta(weeks=n),
        "周": datetime.timedelta(weeks=n),
        "個月": datetime.timedelta(days=30 * n),
        "月": datetime.timedelta(days=30 * n),
        "年": datetime.timedelta(days=365 * n),
    }.get(unit, datetime.timedelta())
    return int((now - delta).timestamp())


def _stars_from_label(label):
    """從 aria-label（如『5 顆星』『評分 4.0』）抽出星數整數。"""
    if not label:
        return 0
    m = re.search(r"(\d+(?:\.\d+)?)", label)
    return int(round(float(m.group(1)))) if m else 0


def scrape_place(query, limit=20, headless=True):
    """爬單一商家。query 可為店名+地址或 place_id。"""
    from playwright.sync_api import sync_playwright

    rating, total, reviews, place_id = None, 0, [], None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=[
            "--no-sandbox", "--disable-blink-features=AutomationControlled",
        ])
        ctx = browser.new_context(
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 1600},
        )
        # 略過歐盟同意牆
        ctx.add_cookies([
            {"name": "CONSENT", "value": "YES+", "domain": ".google.com", "path": "/"},
            {"name": "SOCS", "value": "CAESHAgBEhJnd3NfMjAyNDA", "domain": ".google.com", "path": "/"},
        ])
        page = ctx.new_page()
        page.set_default_timeout(25000)

        try:
            url = ("https://www.google.com/maps/search/"
                   + urllib.parse.quote(query) + "?hl=zh-TW&gl=TW")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)

            # 若落在搜尋結果清單，點第一筆進入商家頁
            try:
                feed = page.query_selector('div[role="feed"]')
                if feed:
                    first = page.query_selector('div[role="feed"] a[href*="/maps/place/"]')
                    if first:
                        first.click()
                        page.wait_for_timeout(3000)
            except Exception:
                pass

            # place_id：從網址抓 data id（!1s0x...:0x...）
            try:
                m = re.search(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)", page.url)
                if m:
                    place_id = m.group(1)
            except Exception:
                pass

            # 平均星等
            for sel in ['div.fontDisplayLarge', 'div.F7nice span[aria-hidden="true"]']:
                el = page.query_selector(sel)
                if el:
                    txt = (el.inner_text() or "").strip()
                    mm = re.search(r"\d+(?:\.\d+)?", txt)
                    if mm:
                        rating = float(mm.group(0))
                        break

            # 總評論數
            body = page.inner_text("body")
            mt = re.search(r"([\d,]+)\s*(?:則評論|則 Google 評論|reviews)", body)
            if mt:
                total = int(mt.group(1).replace(",", ""))

            # 切到「評論」分頁
            for name in ["評論", "Reviews"]:
                tab = page.query_selector(f'button[role="tab"]:has-text("{name}")') \
                    or page.query_selector(f'button:has-text("{name}")')
                if tab:
                    try:
                        tab.click()
                        page.wait_for_timeout(2500)
                        break
                    except Exception:
                        pass

            # 排序：最新
            try:
                sort_btn = page.query_selector('button[aria-label*="排序"]') \
                    or page.query_selector('button:has-text("排序")')
                if sort_btn:
                    sort_btn.click()
                    page.wait_for_timeout(1200)
                    newest = page.query_selector('div[role="menuitemradio"]:has-text("最新")') \
                        or page.query_selector('div[role="menuitem"]:has-text("最新")')
                    if newest:
                        newest.click()
                        page.wait_for_timeout(2500)
            except Exception:
                pass

            # 找可捲動的評論面板並往下捲，載入更多卡片
            scroll_sel = 'div.m6QErb.DxyBCb.kA9KIf.dS8AEf'
            for _ in range(8):
                cards = page.query_selector_all('div.jftiEf, div[data-review-id]')
                if len(cards) >= limit:
                    break
                try:
                    page.eval_on_selector(
                        scroll_sel,
                        "el => el.scrollTo(0, el.scrollHeight)")
                except Exception:
                    page.mouse.wheel(0, 4000)
                page.wait_for_timeout(1800)

            # 展開「全文」按鈕
            for more in page.query_selector_all('button:has-text("全文"), button[aria-label*="顯示更多"]'):
                try:
                    more.click()
                    page.wait_for_timeout(80)
                except Exception:
                    pass

            cards = page.query_selector_all('div.jftiEf, div[data-review-id]')
            for c in cards[:limit]:
                try:
                    author_el = c.query_selector('div.d4r55, .d4r55')
                    author = (author_el.inner_text().strip() if author_el else "匿名") or "匿名"

                    star_el = c.query_selector('span.kvMYJc, [aria-label*="顆星"], [role="img"][aria-label*="星"]')
                    stars = _stars_from_label(star_el.get_attribute("aria-label")) if star_el else 0

                    text_el = c.query_selector('span.wiI7pd, .wiI7pd')
                    text = (text_el.inner_text().strip() if text_el else "")

                    date_el = c.query_selector('span.rsqaWe, .rsqaWe, .xRkPPb')
                    ts = _rel_to_ts(date_el.inner_text()) if date_el else 0

                    reviews.append({"stars": stars, "text": text, "author": author, "ts": ts})
                except Exception:
                    continue

        except Exception as e:
            print(f"  ⚠️ 抓「{query}」失敗：{e}")
        finally:
            ctx.close()
            browser.close()

    if total == 0 and reviews:
        total = len(reviews)
    return rating, total, reviews, place_id or query


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "UG信義永吉店 台北市信義區"
    r, n, revs, pid = scrape_place(q, limit=10, headless=True)
    print(f"rating={r} total={n} place_id={pid} 抓到 {len(revs)} 則")
    for x in revs[:5]:
        print(" ", x["stars"], "★", x["author"], "|", x["text"][:40])
