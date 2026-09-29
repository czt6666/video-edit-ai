#!/usr/bin/env bash
# Local dev bring-up WITHOUT Docker, for the parts we own (login/files/admin).
#   - auth-service   :8091
#   - file-manager   :8092  (serves .local/workspace as the file tree)
#   - dev-router     :8080  (single origin; forward_auth gate like Caddy)
#
# Open http://localhost:8080  ->  redirected to /login.
# Login with admin / admin12345 (from .env AUTH_ADMIN_*), then /files works.
# For the chat workbench (WebSocket), use the Docker stack (./start.sh).
#
# Stop everything:  ./scripts/dev-down.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
set -a; . ./.env; set +a

[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r auth-service/requirements.txt -r file-manager/requirements.txt

mkdir -p .local/dev .local/workspace/{raw,analysis,projects,outputs}

# --- auth-service ----------------------------------------------------------
AUTH_DB_PATH="$REPO/.local/dev/auth.db" \
AUTH_JWT_SECRET="${AUTH_JWT_SECRET}" \
AUTH_ADMIN_USER="${AUTH_ADMIN_USER:-admin}" \
AUTH_ADMIN_PASSWORD="${AUTH_ADMIN_PASSWORD:-admin12345}" \
AUTH_COOKIE_SECURE=false \
nohup "$REPO/.venv/bin/uvicorn" app.main:app --app-dir auth-service \
    --host 127.0.0.1 --port 8091 >/tmp/veai-auth.log 2>&1 &
echo $! > .local/dev/auth.pid

# --- file-manager ----------------------------------------------------------
FM_WORKSPACE_ROOT="$REPO/.local/workspace" \
FM_TRUST_PROXY_AUTH=true \
nohup "$REPO/.venv/bin/uvicorn" app.main:app --app-dir file-manager \
    --host 127.0.0.1 --port 8092 >/tmp/veai-files.log 2>&1 &
echo $! > .local/dev/files.pid

# --- dev router ------------------------------------------------------------
# 8080 is often taken by the media-gateway during dev; use 8088 for the router.
ROUTER_PORT="${ROUTER_PORT:-8088}" \
nohup "$REPO/.venv/bin/python" scripts/dev-router.py >/tmp/veai-router.log 2>&1 &
echo $! > .local/dev/router.pid

sleep 3
echo "auth-service : $(curl -s localhost:8091/health || echo DOWN)"
echo "file-manager : $(curl -s localhost:8092/health || echo DOWN)"
echo
echo "Open  ->  http://localhost:${ROUTER_PORT:-8088}   (login: ${AUTH_ADMIN_USER:-admin} / ${AUTH_ADMIN_PASSWORD:-admin12345})"
echo "Logs  ->  /tmp/veai-auth.log  /tmp/veai-files.log  /tmp/veai-router.log"
