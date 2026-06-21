"""
（選用）在 GitHub Action 內用 Claude 產生 AI 內容，寫回 dashboard.json。
金鑰只從環境變數 ANTHROPIC_API_KEY 讀（GitHub Secret），絕不進前端。
跑法：python collector/ai_report.py（在 google_reviews.py 之後）
"""
import os, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "docs" / "data" / "dashboard.json"
MODEL = "claude-sonnet-4-6"


def _client():
    import anthropic  # pip install anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _ask(cli, prompt, max_tokens=1000):
    msg = cli.messages.create(model=MODEL, max_tokens=max_tokens,
                              messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def build_context(d):
    brands = sorted(d.get("brands", []), key=lambda b: -b["score"])
    lines = [f'{i+1}. {b["name"]}{"(自家)" if b.get("self") else ""} '
             f'熱度{b["score"]} 正{b["pos"]}%/負{b["neg"]}%' for i, b in enumerate(brands)]
    alerts = "\n".join(f'[{a["lv"]}] {a["txt"]}' for a in d.get("alerts", []))
    return "今日聲量熱度榜：\n" + "\n".join(lines) + "\n\n預警：\n" + alerts


def main():
    d = json.loads(DASH.read_text(encoding="utf-8"))
    cli = _client()
    ctx = build_context(d)
    ai = d.get("ai", {})

    ai["daily"] = _ask(cli,
        "你是聯發國際(UG)手搖飲連鎖的營運總監幕僚。根據以下資料寫繁體中文營運日報："
        "BLUF 一句結論，再條列 UG vs 競品、情緒警訊、今天值得看的 2-3 件事、建議行動。320 字內。\n\n" + ctx, 900)

    # VOC 分群（負評）
    negs = [r["text"] for r in d.get("gReviews", []) if r.get("stars", 5) <= 2]
    if negs:
        raw = _ask(cli,
            "把以下 UG 負評做主題聚類，只回 JSON 陣列（不要 markdown）："
            '[{"name":"主題","count":數量,"sample":"代表原文"}]，最多 6 群。\n\n'
            + "\n".join(f"{i+1}. {t}" for i, t in enumerate(negs)), 800)
        try:
            d["voc_clusters"] = json.loads(raw.replace("```json", "").replace("```", "").strip())
        except Exception:
            pass

    # 應對話術：對前兩則最嚴重負評各產一則回覆
    worst = sorted([r for r in d.get("gReviews", []) if r.get("stars", 5) <= 2],
                   key=lambda r: r["stars"])[:2]
    d["negPosts"] = [{
        "src": f'Google 評論 · {r["store"]} ★{r["stars"]}',
        "txt": r["text"],
        "reply": _ask(cli,
            "你是 UG 手搖飲店長。針對以下負評寫繁中公開回覆草稿：誠懇、具體、不卸責、"
            "講清楚改善或補救、80 字內，只回草稿。\n內容：" + r["text"], 400),
    } for r in worst]

    d["ai"] = ai
    DASH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print("AI 內容已寫回 dashboard.json")


if __name__ == "__main__":
    main()
