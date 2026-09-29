#!/usr/bin/env bash
# Agent container entrypoint.
#
# 1. Refresh MANAGED, read-only content (skills / CLAUDE.md / settings) from the
#    image into the persistent ~/.claude volume, without clobbering the user's
#    sessions / memory / auth DB.
# 2. Start claudecodeui in PLATFORM mode (its own login is disabled; our gateway
#    enforces auth). Seed the single platform user + the single /workspace
#    project so there is no "Choose Your Project" step.
set -euo pipefail

CLAUDE_HOME=/home/agent/.claude
mkdir -p "$CLAUDE_HOME/projects" "$CLAUDE_HOME/memory"

# Skills + CLAUDE.md + settings are managed: always overwrite from the image.
rsync -a --delete /opt/agent/claude-home/skills/ "$CLAUDE_HOME/skills/"
cp -f /opt/agent/claude-home/CLAUDE.md "$CLAUDE_HOME/CLAUDE.md"
cp -f /opt/agent/claude-home/settings.json "$CLAUDE_HOME/settings.json"

# Seed memory only if the user has none yet (never overwrite real memory).
if [ ! -f "$CLAUDE_HOME/memory/preferences.md" ]; then
  cp /opt/agent/claude-home/preferences.seed.md "$CLAUDE_HOME/memory/preferences.md"
fi

# The user-provided style skill must stay read-only (must not be modified).
chmod -R a-w "$CLAUDE_HOME/skills/yingshi-jufeng-tim-editor" 2>/dev/null || true

# --- launch claudecodeui (platform mode) -----------------------------------
cd /opt/claudecodeui

: "${SERVER_PORT:=3001}"
: "${WORKSPACES_ROOT:=/workspace}"
: "${DATABASE_PATH:=$CLAUDE_HOME/ccui/auth.db}"
export SERVER_PORT WORKSPACES_ROOT DATABASE_PATH
mkdir -p "$(dirname "$DATABASE_PATH")"

# The image already ran `npm run build`, so launch the compiled server directly.
npm run server &
SERVER_PID=$!

# Wait for the server (and its DB schema) to come up.
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${SERVER_PORT}/api/config" >/dev/null 2>&1 \
     || curl -sf "http://127.0.0.1:${SERVER_PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Seed the platform user (auth is bypassed in platform mode) ...
CCUI_DIR=/opt/claudecodeui node /opt/agent/platform-init.mjs \
  || echo "[entrypoint] platform-init failed (continuing)"

# ... and ensure the single workspace project exists (idempotent).
curl -sf -X POST "http://127.0.0.1:${SERVER_PORT}/api/projects/create-project" \
     -H 'Content-Type: application/json' \
     -d "{\"path\":\"${WORKSPACES_ROOT}\",\"customName\":\"工作台\"}" \
     >/dev/null 2>&1 && echo "[entrypoint] workspace project ready" \
     || echo "[entrypoint] workspace project already exists / create skipped"

# Hand the server the foreground so signals propagate.
wait "$SERVER_PID"
