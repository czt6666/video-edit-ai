#!/usr/bin/env bash
# Refresh MANAGED, read-only content from the image into the persistent
# ~/.claude volume, without clobbering sessions / memory / auth DB.
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

# The user-provided style skill must be read-only (must not be modified).
chmod -R a-w "$CLAUDE_HOME/skills/yingshi-jufeng-tim-editor" 2>/dev/null || true

# Start Claude Code UI. The image already ran `npm run build`, so launch the
# compiled server directly (npm run start would rebuild on every boot).
cd /opt/claudecodeui
exec npm run server
