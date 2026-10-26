#!/usr/bin/env bash
# Make sure Postgres and Redis are reachable for the integration suite. Reuses the Compose
# services when the stack is up; otherwise starts just those two.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG_PORT="${VOS_PG_PORT:-4542}"
REDIS_PORT="${VOS_REDIS_PORT:-4579}"

ready() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

if ready "$PG_PORT" && ready "$REDIS_PORT"; then
  exit 0
fi
"$ROOT/scripts/gen-local-env.sh" >/dev/null
docker compose --env-file "$ROOT/deploy/compose/.env" -f "$ROOT/deploy/compose/compose.yaml" \
  up -d --wait postgres redis
