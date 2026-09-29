#!/usr/bin/env bash
# Bring up the full platform with Docker Compose.
#
#   ./start.sh                 build (if needed) + start all services
#   ./start.sh --build         force a rebuild of local images
#
# Prerequisites (production host):
#   - .env filled in (copy from .env.example)
#   - TOS mounted at /mnt/tos (see rclone/rclone-tos.service)
#   - DNS A record for $DOMAIN -> this host (Caddy issues TLS automatically)
#
# For local development WITHOUT Docker/TLS/rclone, use scripts/dev-up.sh instead.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; . ./.env; set +a

if [ ! -d /mnt/tos ]; then
  echo "WARNING: /mnt/tos is not present. The agent + file-manager expect the" >&2
  echo "         TOS mount there. Start rclone first (rclone/rclone-tos.service)." >&2
fi

BUILD_FLAG="--build"
[ "${1:-}" = "--no-build" ] && BUILD_FLAG=""

echo "==> docker compose up -d ${BUILD_FLAG}"
docker compose up -d ${BUILD_FLAG}

echo
echo "==> Services:"
docker compose ps
echo
echo "Open:   https://${DOMAIN}/          (chat workbench)"
echo "        https://${DOMAIN}/files     (file manager)"
echo "        https://${DOMAIN}/admin     (account management, admin only)"
echo
echo "First login: ${AUTH_ADMIN_USER:-admin} / (AUTH_ADMIN_PASSWORD from .env)"
