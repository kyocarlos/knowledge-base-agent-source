#!/usr/bin/env bash
# Isolated end-to-end check of per-user source credentials with mock sources.
# Builds images from this checkout, generates throwaway keys/certs/secrets,
# runs on an internal network with no published ports, and always cleans up.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$(pwd)"
project="km-cross-cred-sandbox-${UID}-$$"
file="deploy/cross-search-credentials/sandbox-compose.yaml"
work="$(mktemp -d)"
cleanup() {
  docker compose -p "$project" -f "$file" --profile driver down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker image rm -f "${SANDBOX_CROSS_IMAGE:-}" "${SANDBOX_BRIDGE_IMAGE:-}" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

: "${SANDBOX_TEST_IMAGE:?set to an image with the KM Python deps and pytest/uvicorn}"
export SANDBOX_TEST_IMAGE
export SANDBOX_CROSS_IMAGE="km-cross-search:sandbox-$$" SANDBOX_BRIDGE_IMAGE="km-cross-bridge:sandbox-$$"
docker build -q -t "$SANDBOX_CROSS_IMAGE" -f cross_search/Dockerfile "$root" >/dev/null
docker build -q -t "$SANDBOX_BRIDGE_IMAGE" -f Dockerfile.cross-bridge "$root" >/dev/null

mkdir -p "$work/keys/public" "$work/keys/private" "$work/certs"
openssl genpkey -algorithm X25519 -out "$work/keys/private/sandbox1.pem" 2>/dev/null
openssl pkey -in "$work/keys/private/sandbox1.pem" -pubout -out "$work/keys/public/sandbox1.pem"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=sandbox-ca" -keyout "$work/certs/ca.key" -out "$work/certs/ca.crt" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=mock-sources.sandbox.test" -keyout "$work/certs/mock.key" -out "$work/certs/mock.csr" 2>/dev/null
printf 'subjectAltName=DNS:mock-sources.sandbox.test\n' > "$work/certs/san.ext"
openssl x509 -req -in "$work/certs/mock.csr" -CA "$work/certs/ca.crt" -CAkey "$work/certs/ca.key" -CAcreateserial -days 1 -extfile "$work/certs/san.ext" -out "$work/certs/mock.crt" 2>/dev/null
chmod 0600 "$work"/keys/private/*; chmod 0644 "$work"/keys/public/* "$work"/certs/*.crt "$work"/certs/mock.key

export SANDBOX_KEY_DIR="$work/keys" SANDBOX_CERT_DIR="$work/certs"
export SANDBOX_DB_PASSWORD="$(openssl rand -hex 16)" SANDBOX_CONTROL_KEY="$(openssl rand -hex 32)"
export SANDBOX_ENTRY_KEY="$(openssl rand -hex 32)" SANDBOX_BRIDGE_SECRET="$(openssl rand -hex 32)"

docker compose -p "$project" -f "$file" up -d --wait control-db redis
docker compose -p "$project" -f "$file" exec -T control-db psql -q -v ON_ERROR_STOP=1 -U km_control_app -d km_control < deploy/cross-search-credentials/control-base-schema.sql
docker compose -p "$project" -f "$file" exec -T control-db psql -q -v ON_ERROR_STOP=1 -U km_control_app -d km_control < migrations/20261015_km_source_credentials.sql
docker compose -p "$project" -f "$file" up -d mock-sources control bridge cross-api cross-worker
docker compose -p "$project" -f "$file" --profile driver run --rm driver
# No user secret or private key material may appear in any service log.
if docker compose -p "$project" -f "$file" logs --no-color 2>&1 | grep -E -- '-pass|-pat|PRIVATE KEY|km-src-cred-v1\.' >/dev/null; then
  echo "FAIL secret material found in service logs"; exit 1
fi
echo "PASS no secret material in service logs"
