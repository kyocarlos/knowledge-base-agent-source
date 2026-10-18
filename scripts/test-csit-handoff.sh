#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/check-csit-contract-sync.py
project="km-handoff-test-${UID}-$$"
file="deploy/csit-integration-v1/test-compose.yaml"
cleanup() { docker compose -p "$project" -f "$file" down --volumes --remove-orphans; }
trap cleanup EXIT
docker compose -p "$project" -f "$file" build tests
docker compose -p "$project" -f "$file" up -d --wait db graph
docker compose -p "$project" -f "$file" run --rm --no-deps tests
docker compose -p "$project" -f "$file" run --rm --no-deps tests python -m src.csit_integration_v1.offline_verify
