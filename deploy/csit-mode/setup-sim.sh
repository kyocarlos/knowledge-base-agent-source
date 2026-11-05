#!/usr/bin/env bash
# One-time preparation for the simulated CSIT mode (idempotent). Nothing here touches the real mode's data.
#  - PostgreSQL schema csit_sim in km_control with the Test Report v1 and spec v1.3 tables (same migrations as the public schema)
#  - Qdrant collection km_csit_docs_sim (same vector settings as the real collection)
#  - the simulated KM client secret, and sim.db.env (the DB URL with search_path=csit_sim)
set -euo pipefail
export KM_MODE_DIR="${KM_MODE_DIR:-$HOME/.km-control/csit-mode}"
ENVF="${KM_CSIT_DEPLOY_ENV:-$HOME/.km-control/csit-integration-v1-20261007/deploy-da40.env}"
DB_CONTAINER="${KM_CONTROL_DB_CONTAINER:-km-control-3030-control_db-1}"
MIG="${KM_MIGRATIONS_DIR:-$KM_MODE_DIR/migrations}"
# shellcheck disable=SC1091
source "$KM_MODE_DIR/images.env"
umask 077
mkdir -p "$KM_MODE_DIR/sim" "$KM_MODE_DIR/sim-data"
if [ ! -s "$KM_MODE_DIR/sim/km-client-secret" ]; then
  head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$KM_MODE_DIR/sim/km-client-secret"
fi
chmod 600 "$KM_MODE_DIR/sim/km-client-secret"
[ -f "$KM_MODE_DIR/sim/ca.pem" ] || : > "$KM_MODE_DIR/sim/ca.pem"

# sim.db.env: the real DB URL (read from the protected env file, never printed) plus search_path
ENVFILE=$(grep -E '^KM_CSIT_ENV_FILE=' "$ENVF" | head -1 | cut -d= -f2-)
URL=$(grep -E '^KM_CSIT_DB_URL=' "$ENVFILE" | head -1 | cut -d= -f2-)
case "$URL" in *\?*) echo "DB URL already has a query string" >&2; exit 1 ;; esac
printf 'KM_CSIT_DB_URL=%s?options=-c%%20search_path%%3Dcsit_sim\n' "$URL" > "$KM_MODE_DIR/sim.db.env"
chmod 600 "$KM_MODE_DIR/sim.db.env"

docker exec -i "$DB_CONTAINER" psql -U km_control_app -d km_control -v ON_ERROR_STOP=1 -q -c "CREATE SCHEMA IF NOT EXISTS csit_sim"
for f in 20261007_csit_integration_v1.sql 20261014_csit_integration_v1_nullable_lineage.sql 20261104_csit_document_library_v1.sql 20261105_csit_integration_v2.sql; do
  docker exec -e PGOPTIONS="-c search_path=csit_sim" -i "$DB_CONTAINER" psql -U km_control_app -d km_control -v ON_ERROR_STOP=1 -q < "$MIG/$f"
  echo "applied $f to csit_sim"
done
# The Test Report v1 worker reads km_audit_events when it claims a job (resume bookkeeping). An empty copy of its structure keeps that lookup inside csit_sim
# instead of widening the search_path to the real tables.
docker exec -e PGOPTIONS="-c search_path=csit_sim" -i "$DB_CONTAINER" psql -U km_control_app -d km_control -v ON_ERROR_STOP=1 -q \
  -c "CREATE TABLE IF NOT EXISTS km_audit_events (LIKE public.km_audit_events INCLUDING ALL)"
docker exec -e PGOPTIONS="-c search_path=csit_sim" -i "$DB_CONTAINER" psql -U km_control_app -d km_control -At \
  -c "select count(*) || ' km_csit tables in csit_sim' from information_schema.tables where table_schema='csit_sim' and table_name like 'km_csit_%'"

docker run --rm --network km-da40_default -i --entrypoint python "$KM_CSIT_API_IMAGE" - <<'PY'
import json,urllib.request
base="http://km-da40-qdrant-1:6333"
def call(m,p,b=None):
    r=urllib.request.Request(base+p,method=m,data=json.dumps(b).encode() if b else None,headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r))
vec=call("GET","/collections/knowledge_base")["result"]["config"]["params"]["vectors"]
try:
    call("GET","/collections/km_csit_docs_sim");print("km_csit_docs_sim exists")
except Exception:
    print("created km_csit_docs_sim:",call("PUT","/collections/km_csit_docs_sim",{"vectors":vec})["status"])
PY
echo "sim setup done"
