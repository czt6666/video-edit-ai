#!/usr/bin/env bash
# Stop the platform.
#   ./stop.sh              stop + remove containers (volumes kept)
#   ./stop.sh --volumes    also remove named volumes (DESTROYS accounts + agent
#                          sessions; does NOT touch TOS data, which lives on the
#                          host mount, not in a volume)
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--volumes" ]; then
  echo "==> docker compose down -v (removing volumes)"
  docker compose down -v
else
  echo "==> docker compose down"
  docker compose down
fi
