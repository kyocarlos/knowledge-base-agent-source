#!/usr/bin/env bash
# Switch the KM DEV CSIT integration between the real CSIT and the CSIT simulator.
#   csit-mode.sh status
#   csit-mode.sh real|sim [--force]
#   csit-mode.sh reapply            recreate api and worker for the current mode (e.g. after a new image tag in images.env)
# Switching recreates the api and worker containers with the other mode's settings (identity authority, CSIT address, schema, collection, storage).
# It refuses while the current mode still has work in flight (jobs, deletions, undelivered callbacks) unless --force. There is no runtime switch inside KM.
set -euo pipefail
export KM_MODE_DIR="${KM_MODE_DIR:-$HOME/.km-control/csit-mode}"
DEPLOY="${KM_DEPLOY_DIR:-$HOME/knowledge-base/deploy/csit-integration-v1}"
ENVF="${KM_CSIT_DEPLOY_ENV:-$HOME/.km-control/csit-integration-v1-20261007/deploy-da40.env}"
DB_CONTAINER="${KM_CONTROL_DB_CONTAINER:-km-control-3030-control_db-1}"
PROJECT=km-csit-v1-dev
# shellcheck disable=SC1091
source "$KM_MODE_DIR/images.env"   # KM_CSIT_API_IMAGE, KM_CSIT_WORKER_IMAGE, KM_CSIT_SIM_IMAGE
export KM_CSIT_API_IMAGE KM_CSIT_WORKER_IMAGE KM_CSIT_SIM_IMAGE

compose_km() {  # compose_km <real|sim> <docker compose args...>
  local mode=$1; shift
  if [ "$mode" = real ]; then
    (cd "$DEPLOY" && docker compose --profile m2m-ready -p "$PROJECT" --env-file "$ENVF" -f compose.yaml -f "$KM_MODE_DIR/compose-real.override.yml" "$@")
  else
    (cd "$KM_MODE_DIR" && docker compose --profile m2m-ready -p "$PROJECT" --env-file "$ENVF" -f compose-sim.yml "$@")
  fi
}
compose_sim() { (cd "$KM_MODE_DIR" && docker compose -p km-csit-sim --env-file "$ENVF" -f compose-simulator.yml "$@"); }

current_mode() {
  local m
  m=$(docker exec km-csit-integration-api python -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)).get('csitMode','real'))" 2>/dev/null || true)
  echo "${m:-unknown}"
}

prepare_sim_ca() {
  # SSL_CERT_FILE replaces the whole trust list, and the worker also needs public HTTPS (model download): public roots + the simulator's CA in one file.
  mkdir -p "$KM_MODE_DIR/sim"
  [ -s "$KM_MODE_DIR/sim-data/tls/ca.pem" ] || { echo "the simulator has not created its CA yet" >&2; return 1; }
  { docker run --rm --network none --entrypoint python "$KM_CSIT_API_IMAGE" -c "import certifi;print(open(certifi.where()).read())"
    cat "$KM_MODE_DIR/sim-data/tls/ca.pem"; } > "$KM_MODE_DIR/sim/ca.pem.new"
  mv "$KM_MODE_DIR/sim/ca.pem.new" "$KM_MODE_DIR/sim/ca.pem"
}

busy() {  # busy <real|sim> -> number of things in flight in that mode's schema
  local schema=public
  [ "$1" = sim ] && schema=csit_sim
  docker exec -e PGOPTIONS="-c search_path=$schema" -i "$DB_CONTAINER" psql -U km_control_app -d km_control -At <<'SQL'
select (select count(*) from km_csit_ingestion_jobs where status in ('Accepted','Processing'))
     + (select count(*) from km_csit_doclib_jobs where status in ('Accepted','Processing'))
     + (select count(*) from km_csit_deletion_jobs where status in ('Accepted','Processing'))
     + (select count(*) from km_csit_callback_deliveries where status in ('Pending','Delivering'))
     + (select count(*) from km_csit_v13_callbacks where status in ('Pending','Delivering'));
SQL
}

wait_api() {  # wait_api <mode>
  for _ in $(seq 1 40); do
    if [ "$(current_mode)" = "$1" ]; then return 0; fi
    sleep 3
  done
  echo "api did not report csitMode=$1" >&2
  return 1
}

status() {
  local m
  m=$(current_mode)
  echo "mode:        $m"
  echo "api:         $(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} image={{.Config.Image}}' km-csit-integration-api 2>/dev/null || echo missing)"
  echo "worker:      $(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' ${PROJECT}-worker-1 2>/dev/null || echo missing)"
  echo "simulator:   $(docker inspect -f '{{.State.Status}}' csit-sim 2>/dev/null || echo 'not running')"
  echo "in flight:   real=$(busy real 2>/dev/null || echo '?')  sim=$(busy sim 2>/dev/null || echo '?')"
  if [ -f "$KM_MODE_DIR/state.json" ]; then echo "last switch: $(cat "$KM_MODE_DIR/state.json")"; fi
  return 0
}

switch() {
  local target=$1 force=${2:-} cur n
  cur=$(current_mode)
  if [ "$cur" = "$target" ]; then echo "already in $target mode"; status; return 0; fi
  if [ "$cur" != real ] && [ "$cur" != sim ]; then
    echo "cannot tell the current mode ($cur): is km-csit-integration-api running?" >&2
    [ "$force" = --force ] || exit 1
  fi
  n=$(busy "$cur" || echo "?")
  if [ "$n" != 0 ] && [ "$force" != --force ]; then
    echo "refused: $n item(s) still in flight in $cur mode (jobs, deletions or undelivered callbacks). Wait, or use --force." >&2
    exit 2
  fi
  echo "switching $cur -> $target (in flight in $cur: $n)"
  if [ "$target" = sim ]; then
    mkdir -p "$KM_MODE_DIR/sim-data"
    echo "starting the simulator"
    compose_sim up -d --no-build --pull never csit-sim
    for _ in $(seq 1 40); do [ -s "$KM_MODE_DIR/sim-data/tls/ca.pem" ] && break; sleep 2; done
    [ -s "$KM_MODE_DIR/sim-data/tls/ca.pem" ] || { echo "simulator did not create its CA" >&2; exit 1; }
    prepare_sim_ca
  fi
  docker rm -f "${PROJECT}-worker-1" >/dev/null 2>&1 || true
  compose_km "$target" up -d --wait --no-deps --no-build --pull never api
  wait_api "$target"
  compose_km "$target" up -d --no-deps --no-build --pull never worker
  for _ in $(seq 1 30); do
    [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${PROJECT}-worker-1" 2>/dev/null)" = healthy ] && break
    sleep 4
  done
  if [ "$target" = real ]; then compose_sim down >/dev/null 2>&1 || docker rm -f csit-sim >/dev/null 2>&1 || true; fi
  printf '{"mode":"%s","at":"%s","from":"%s"}\n' "$target" "$(date -u +%FT%TZ)" "$cur" > "$KM_MODE_DIR/state.json"
  status
}

reapply() {
  local cur
  cur=$(current_mode)
  { [ "$cur" = real ] || [ "$cur" = sim ]; } || { echo "cannot tell the current mode ($cur)" >&2; exit 1; }
  if [ "$cur" = sim ]; then prepare_sim_ca; fi
  docker rm -f "${PROJECT}-worker-1" >/dev/null 2>&1 || true
  compose_km "$cur" up -d --wait --no-deps --no-build --pull never api
  wait_api "$cur"
  compose_km "$cur" up -d --no-deps --no-build --pull never worker
  for _ in $(seq 1 30); do
    [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${PROJECT}-worker-1" 2>/dev/null)" = healthy ] && break
    sleep 4
  done
  status
}

case "${1:-}" in
  status) status ;;
  reapply) reapply ;;
  real|sim) switch "$1" "${2:-}" ;;
  *) echo "usage: $0 status | reapply | real [--force] | sim [--force]" >&2; exit 64 ;;
esac
