#!/usr/bin/env bash
# Local debug bring-up WITHOUT Docker/rclone/Caddy:
#   - media-gateway (uvicorn)          :8080   (real TOS/Doubao/Ark)
#   - CloudCLI UI (claudecodeui)       :3001   (LLM via temp gateway)
#   - isolated HOME so your real ~/.claude is untouched
#   - .local/workspace as the shared file tree (stands in for /mnt/tos)
#
# One-time prep is handled automatically. Open http://localhost:3001 after.
# Stop everything:  pkill -f "uvicorn app:app"; pkill -f "npm run server"
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
set -a; . ./.env; set +a

# --- media-gateway ---------------------------------------------------------
if ! curl -s http://127.0.0.1:8080/health >/dev/null 2>&1; then
  [ -d .venv ] || python3 -m venv .venv
  ./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r media-gateway/requirements.txt
  ( cd media-gateway && MG_TOKEN="$MEDIA_GATEWAY_TOKEN" \
      nohup "$REPO/.venv/bin/uvicorn" app:app --host 127.0.0.1 --port 8080 >/tmp/mg.log 2>&1 & )
  sleep 3
fi
echo "media-gateway: $(curl -s http://127.0.0.1:8080/health)"

# --- CloudCLI UI (build once) ---------------------------------------------
if [ ! -d .local/claudecodeui/dist-server ]; then
  echo "First run: cloning + building claudecodeui (a few minutes)…"
  [ -d .local/claudecodeui ] || git clone --depth 1 https://github.com/siteboon/claudecodeui .local/claudecodeui
  ( cd .local/claudecodeui
    # 1.17.x ripgrep hits GitHub API (403 in CN); 1.18.0 bundles binaries.
    python3 -c "import json;d=json.load(open('package.json'));d['dependencies']['@vscode/ripgrep']='^1.18.0';json.dump(d,open('package.json','w'),indent=2)"
    npm install --registry=https://registry.npmmirror.com --fetch-retries=8 --fetch-timeout=120000
    npm run build )
fi

# seed isolated claude home (managed content only; keeps sessions/memory)
mkdir -p .local/home/.claude/{projects,memory} .local/workspace/{raw,analysis,projects,outputs}
cp -f agent/claude/CLAUDE.md .local/home/.claude/CLAUDE.md
cp -f agent/claude/settings.json .local/home/.claude/settings.json
[ -f .local/home/.claude/memory/preferences.md ] || cp agent/claude/preferences.seed.md .local/home/.claude/memory/preferences.md
rsync -a --delete agent/skills/ .local/home/.claude/skills/

cd .local/claudecodeui
export HOME="$REPO/.local/home"
export SERVER_PORT=3001
export WORKSPACES_ROOT="$REPO/.local/workspace"
export WORKSPACE_ROOT="$REPO/.local/workspace"
export DATABASE_PATH="$REPO/.local/home/ccui-auth.db"
export JWT_SECRET="$CCUI_JWT_SECRET"
# LLM via the temp gateway (Anthropic-compatible at /v1/messages)
export ANTHROPIC_BASE_URL="$DEV_OPENAI_BASE_URL"
export ANTHROPIC_AUTH_TOKEN="$DEV_OPENAI_API_KEY"
export ANTHROPIC_MODEL="$DEV_OPENAI_MODEL"
export MEDIA_GATEWAY_URL="http://127.0.0.1:8080"
export MEDIA_GATEWAY_TOKEN="$MEDIA_GATEWAY_TOKEN"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export PATH="$REPO/agent/bin:$PATH"

echo "CloudCLI UI -> http://localhost:3001  (first run: create one account)"
exec npm run server
