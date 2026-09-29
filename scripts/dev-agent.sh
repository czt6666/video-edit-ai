#!/usr/bin/env bash
# Run claudecodeui locally in PLATFORM mode (mirrors agent/entrypoint.sh) so the
# chat workbench can be validated without Docker. Requires a platform-mode build
# (VITE_IS_PLATFORM=true npm run build) in .local/claudecodeui.
#
#   ./scripts/dev-agent.sh        # runs on :3001 (open directly; no login)
#
# LLM is routed through the temp dev gateway from .env (Anthropic-compatible).
# Stop with:  pkill -f "npm run server"
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
set -a; . ./.env; set +a

CCUI="$REPO/.local/claudecodeui"
[ -d "$CCUI/dist" ] || { echo "No build found. Run: (cd $CCUI && VITE_IS_PLATFORM=true npm run build)"; exit 1; }

# Inject unified cross-navigation into the built index (idempotent).
node "$REPO/agent/ccui-inject-nav.mjs" "$CCUI/dist/index.html" || true

export HOME="$REPO/.local/home"
export SERVER_PORT=3001
export WORKSPACES_ROOT="$REPO/.local/workspace"
export DATABASE_PATH="$REPO/.local/dev/ccui.db"
export VITE_IS_PLATFORM=true
# LLM via the temp gateway (Anthropic-compatible at /v1/messages)
export ANTHROPIC_BASE_URL="${DEV_OPENAI_BASE_URL:-}"
export ANTHROPIC_AUTH_TOKEN="${DEV_OPENAI_API_KEY:-}"
export ANTHROPIC_MODEL="${DEV_OPENAI_MODEL:-}"
export MEDIA_GATEWAY_URL="http://127.0.0.1:8080"
export MEDIA_GATEWAY_TOKEN="${MEDIA_GATEWAY_TOKEN:-}"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export PATH="$REPO/agent/bin:$PATH"

mkdir -p "$REPO/.local/dev" "$HOME/.claude/"{projects,memory} "$WORKSPACES_ROOT"/{raw,analysis,projects,outputs}
cp -f agent/claude/CLAUDE.md "$HOME/.claude/CLAUDE.md"
cp -f agent/claude/settings.json "$HOME/.claude/settings.json"
[ -f "$HOME/.claude/memory/preferences.md" ] || cp agent/claude/preferences.seed.md "$HOME/.claude/memory/preferences.md"
rsync -a --delete agent/skills/ "$HOME/.claude/skills/"
chmod -R a-w "$HOME/.claude/skills/yingshi-jufeng-tim-editor" 2>/dev/null || true

cd "$CCUI"
echo "Starting claudecodeui (platform mode) on :$SERVER_PORT ..."
nohup npm run server >/tmp/veai-agent.log 2>&1 &
echo $! > "$REPO/.local/dev/agent.pid"

for i in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$SERVER_PORT/" >/dev/null 2>&1 && break
  sleep 1
done

CCUI_DIR="$CCUI" node "$REPO/agent/platform-init.mjs" || echo "platform-init failed"
curl -sf -X POST "http://127.0.0.1:$SERVER_PORT/api/projects/create-project" \
  -H 'Content-Type: application/json' \
  -d "{\"path\":\"$WORKSPACES_ROOT\",\"customName\":\"工作台\"}" >/dev/null 2>&1 \
  && echo "workspace project ready" || echo "project create skipped/exists"

echo "Open http://localhost:$SERVER_PORT  (platform mode: no login). Log: /tmp/veai-agent.log"
