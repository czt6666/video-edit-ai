#!/usr/bin/env bash
# Local debug: run ONLY media-gateway (no Docker) against real provider keys.
# Reads .env, maps MEDIA_GATEWAY_TOKEN -> MG_TOKEN, serves on 127.0.0.1:8080.
#   ./scripts/run-media-gateway-local.sh
# Then, in another shell:
#   TOK=$(grep MEDIA_GATEWAY_TOKEN .env | cut -d= -f2)
#   curl -s localhost:8080/health
#   curl -s -X POST localhost:8080/vlm -H "Authorization: Bearer $TOK" \
#        -H 'Content-Type: application/json' \
#        -d '{"images":["<base64>"],"prompt":"这是什么？"}'
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r media-gateway/requirements.txt
set -a; . ./.env; export MG_TOKEN="$MEDIA_GATEWAY_TOKEN"; set +a
exec ./.venv/bin/uvicorn app:app --app-dir media-gateway --host 127.0.0.1 --port 8080 --reload
