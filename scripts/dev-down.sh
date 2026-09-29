#!/usr/bin/env bash
# Stop the local (no-Docker) dev processes started by dev-up.sh.
set -uo pipefail
cd "$(dirname "$0")/.."
for name in router files auth; do
  pidfile=".local/dev/${name}.pid"
  if [ -f "$pidfile" ]; then
    kill "$(cat "$pidfile")" 2>/dev/null && echo "stopped ${name}" || true
    rm -f "$pidfile"
  fi
done
# Belt-and-suspenders in case pidfiles are stale.
pkill -f "scripts/dev-router.py" 2>/dev/null || true
pkill -f "app-dir auth-service" 2>/dev/null || true
pkill -f "app-dir file-manager" 2>/dev/null || true
echo "done"
