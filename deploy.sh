#!/usr/bin/env bash
# UG 門市 Google 評論監測 — 一鍵部署
# 用法：在「你自己的電腦」、專案根目錄下執行（你已 gh auth login）
#   bash deploy.sh
set -euo pipefail

REPO="ug-review-monitor"

# ── 0. 安全護欄：commit 前先掃有沒有金鑰被硬寫進檔案（ug-it-security 零容忍）──
echo "▶ 掃描是否有金鑰外洩風險…"
if grep -rIn --exclude-dir=.git -E '(OUTSCRAPER|api[_-]?key|secret|token)\s*[:=]\s*["'\''][A-Za-z0-9_\-]{16,}' . ; then
  echo "⚠️  上面這些行疑似硬寫了金鑰／token，請先移到環境變數再跑。中止。"
  exit 1
fi

# ── 0b. 確保不會 commit 到本機雜物 / 環境檔 ──
if [ ! -f .gitignore ]; then
  cat > .gitignore <<'EOF'
.env
.env.local
*.key
__pycache__/
*.pyc
.DS_Store
EOF
  echo "▶ 已建立 .gitignore"
fi

# ── 1. git init / add / commit ──
if [ ! -d .git ]; then git init; fi
git branch -M main            # 強制主分支叫 main（Pages 與排程都指向 main）
git add -A
git commit -m "Initial commit: UG review monitor" || echo "（沒有新變更可 commit，略過）"

# ── 2. 建立公開 repo 並 push ──
gh repo create "$REPO" --public --source=. --remote=origin --push

OWNER="$(gh api user --jq .login)"
echo "▶ GitHub 帳號：$OWNER"

# ── 3. 設定金鑰（互動式，金鑰不進檔案、不進指令歷史）──
echo "▶ 接下來會跳出 'Paste your secret:'，請直接貼上 OUTSCRAPER_API_KEY 後按 Enter"
gh secret set OUTSCRAPER_API_KEY

# ── 3a.（選用）AI 內容金鑰；不需要就直接按 Enter 跳過 ──
read -p "要設定 ANTHROPIC_API_KEY 啟用 AI 日報嗎？(y/N) " ANS
if [[ "$ANS" =~ ^[Yy]$ ]]; then
  echo "▶ 貼上 ANTHROPIC_API_KEY 後按 Enter"
  gh secret set ANTHROPIC_API_KEY
fi

# ── 3b.（補丁）讓 Actions 有寫入權限，否則每天抓完 commit 回 repo 會默默失敗 ──
gh api -X PUT "repos/$OWNER/$REPO/actions/permissions/workflow" \
  -f default_workflow_permissions=write >/dev/null \
  && echo "▶ 已開啟 Actions 寫入權限" \
  || echo "⚠️  無法自動設定 Actions 權限 → 手動：Settings → Actions → General → Workflow permissions → Read and write"

# ── 4. 啟用 GitHub Pages（main 分支 /docs）──
echo '{"source":{"branch":"main","path":"/docs"}}' \
  | gh api -X POST "repos/$OWNER/$REPO/pages" --input - >/dev/null 2>&1 \
  && echo "▶ Pages 已啟用（main /docs）" \
  || echo "⚠️  Pages API 失敗（常見：需等首次 push 生效）→ 手動：Settings → Pages，Source 選 main、資料夾 /docs"

# ── 5. 跑第一次抓取 ──
gh workflow run scrape.yml \
  && echo "▶ 已觸發 scrape.yml（去 Actions 分頁看執行狀況）" \
  || echo "⚠️  workflow run 失敗 → 確認 scrape.yml 的 on: 裡有 'workflow_dispatch:'，且已 push 到 main"

# ── 6. 印出儀表板網址 ──
echo ""
echo "════════════════════════════════════════"
echo "  儀表板網址（Pages 第一次 build 約等 1–2 分鐘）："
echo "  https://$OWNER.github.io/$REPO/"
echo "════════════════════════════════════════"
