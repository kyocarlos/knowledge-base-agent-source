#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="km-handoff-test-${UID}-$$"
file="deploy/csit-integration-v1/test-compose.yaml"
cleanup() { docker compose -p "$project" -f "$file" down --volumes --remove-orphans; }
trap cleanup EXIT
docker compose -p "$project" -f "$file" build tests
docker compose -p "$project" -f "$file" up -d --wait db graph
docker compose -p "$project" -f "$file" run --rm --no-deps tests
