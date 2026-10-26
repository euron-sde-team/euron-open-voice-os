#!/usr/bin/env bash
# Run the API integration suite under every backend combination the app supports:
#
#   cache:   Redis                  | none at all (in-process, Redis is optional)
#   keys:    local AES-GCM key      | AWS KMS (Floci)
#   storage: local disk             | Amazon S3 (Floci)
#
# Needs the local stack (make up): Floci with the local-floci Terraform applied.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FLOCI_URL="http://localhost:${VOS_FLOCI_PORT:-4566}"

if ! curl -sf -o /dev/null "$FLOCI_URL/"; then
  echo "Floci is not reachable at $FLOCI_URL. Start the stack first: make up" >&2
  exit 1
fi
"$ROOT/scripts/test-db.sh"

export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1
export TEST_AWS_ENDPOINT="$FLOCI_URL"
failed=()
runs=0
for cache in redis memory; do
  for keys in local kms; do
    for storage in local s3; do
      runs=$((runs + 1))
      echo
      echo "== cache=$cache keys=$keys storage=$storage"
      if ! (cd "$ROOT/apps/api" && TEST_CACHE=$cache TEST_KEY_MODE=$keys TEST_STORAGE=$storage \
            uv run --extra runtime --extra speech pytest tests/integration -q -p no:warnings); then
        failed+=("cache=$cache keys=$keys storage=$storage")
      fi
    done
  done
done
echo
if ((${#failed[@]})); then
  printf 'matrix: FAILED for %s\n' "${failed[@]}"
  exit 1
fi
echo "matrix: all $runs combinations passed"
