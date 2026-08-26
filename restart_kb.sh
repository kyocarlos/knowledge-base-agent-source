#!/usr/bin/env bash
# Safe WP0/WP1 lifecycle helper for the knowledge-base production stack.

set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MODE="status"
MODE_SET=false
RUNTIME_ENV_FILE="${KB_RUNTIME_ENV_FILE:-}"
CHECKPOINT=""
CONFIRM_DEPLOY=""
ALLOW_DIRTY=false
WAIT_TIMEOUT="${KB_RESTART_WAIT_TIMEOUT_SECONDS:-120}"
BASE_URL="${KB_INTERNAL_BASE_URL:-https://127.0.0.1:${KB_HTTPS_PORT:-3030}}"
EXTERNAL_URL="${KB_EXTERNAL_URL:-$BASE_URL}"
DIRECT_BACKEND_URL="${KB_DIRECT_BACKEND_URL:-http://127.0.0.1:8000}"
FRONTEND_BUILD_DIR="${KB_FRONTEND_BUILD_DIR:-$ROOT_DIR/.frontend-build-runtime-user8}"
REPORT_ENV_FILE="${KB_REPORT_ENV_FILE:-$ROOT_DIR/config/report-ingest.env}"
REPORT_ENV_EXAMPLE="${KB_REPORT_ENV_EXAMPLE:-$ROOT_DIR/config/report-ingest.env.example}"
BACKUP_ROOT="${KB_BACKUP_ROOT:-$HOME/kb-pre-wp01-backups}"
COMPOSE=(docker compose)
APP_SERVICES=(web celery_search_worker celery_ingest_worker celery_beat nginx)
APP_CONTAINERS=(kb-web kb-celery-search kb-celery-ingest kb-celery-beat kb-nginx)

usage() {
    cat <<'EOF'
Usage:
  ./restart_kb.sh [--status]
  ./restart_kb.sh --restart [--env-file FILE]
  ./restart_kb.sh --deploy --confirm-deploy DEPLOY_WP01 [options]

Modes:
  --status       Read-only WP0/WP1 health, worker, queue and WebSocket checks.
                 This is the default when no mode is supplied.
  --restart      Restart application containers only. It never rebuilds images
                 and never removes Redis, Neo4j, Qdrant or PostgreSQL.
  --deploy       Create/use a rollback checkpoint, build a candidate image,
                 recreate application containers and run WP0/WP1 gates.

Deploy options:
  --confirm-deploy DEPLOY_WP01  Required production deployment confirmation.
  --checkpoint DIR              Reuse an existing verified checkpoint.
  --allow-dirty                 Permit tracked source changes in the candidate.

Common options:
  --env-file FILE               Load an additional protected runtime env file.
  --wait-timeout SECONDS        Readiness timeout (default: 120).
  -h, --help                    Show this help.

The script always aborts restart/deploy when Celery has active, reserved,
scheduled or queued work. It does not provide a force option by design.
EOF
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '\n== %s ==\n' "$*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

load_env_file() {
    local env_file="$1"
    [[ -f "$env_file" ]] || return 0
    printf 'Loading runtime environment: %s\n' "$env_file"
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
}

parse_args() {
    while (($#)); do
        case "$1" in
            --status|--restart|--deploy)
                [[ "$MODE_SET" == false ]] || fail "select exactly one mode"
                MODE="${1#--}"
                MODE_SET=true
                ;;
            --env-file)
                (($# >= 2)) || fail "--env-file requires a value"
                RUNTIME_ENV_FILE="$2"
                shift
                ;;
            --checkpoint)
                (($# >= 2)) || fail "--checkpoint requires a value"
                CHECKPOINT="$2"
                shift
                ;;
            --confirm-deploy)
                (($# >= 2)) || fail "--confirm-deploy requires a value"
                CONFIRM_DEPLOY="$2"
                shift
                ;;
            --allow-dirty)
                ALLOW_DIRTY=true
                ;;
            --wait-timeout)
                (($# >= 2)) || fail "--wait-timeout requires a value"
                WAIT_TIMEOUT="$2"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                fail "unknown argument: $1"
                ;;
        esac
        shift
    done

    [[ "$WAIT_TIMEOUT" =~ ^[1-9][0-9]*$ ]] || fail "--wait-timeout must be a positive integer"
    if [[ -n "$RUNTIME_ENV_FILE" && ! -f "$RUNTIME_ENV_FILE" ]]; then
        fail "runtime env file does not exist: $RUNTIME_ENV_FILE"
    fi
}

ensure_report_env() {
    if [[ -n "${KB_REPORT_DB_PASSWORD:-}" ]]; then
        return 0
    fi
    if [[ -f "$REPORT_ENV_FILE" ]]; then
        load_env_file "$REPORT_ENV_FILE"
    fi
    [[ -n "${KB_REPORT_DB_PASSWORD:-}" ]] || fail \
        "KB_REPORT_DB_PASSWORD is missing; configure $REPORT_ENV_FILE from $REPORT_ENV_EXAMPLE"
}

compose_preflight() {
    info "Configuration preflight"
    load_env_file "$ROOT_DIR/.env"
    [[ -z "$RUNTIME_ENV_FILE" ]] || load_env_file "$RUNTIME_ENV_FILE"
    ensure_report_env
    [[ -n "${NEO4J_PASSWORD:-}" ]] || fail \
        "NEO4J_PASSWORD is missing; no container has been changed"
    "${COMPOSE[@]}" config --quiet
    validate_shared_job_ledger_config
    validate_release_metadata_config
    printf 'Compose configuration: PASS\n'
}

validate_release_metadata_config() {
    local metadata_values config_json
    metadata_values="${KM_GIT_COMMIT:-}${KM_RELEASE_ID:-}${KM_IMAGE_DIGEST:-}${KM_BUILD_TIMESTAMP:-}"
    if [[ -z "$metadata_values" ]]; then
        printf 'Release metadata: not configured (development/runtime compatibility mode)\n'
        return 0
    fi
    [[ -n "${KM_GIT_COMMIT:-}" && -n "${KM_RELEASE_ID:-}" && \
       -n "${KM_IMAGE_DIGEST:-}" && -n "${KM_BUILD_TIMESTAMP:-}" ]] || fail \
        "release metadata must provide commit, release ID, image digest, and build timestamp together"
    config_json="$("${COMPOSE[@]}" --profile scheduler config --format json)" || fail \
        "unable to render Compose JSON for release metadata validation"
    python3 "$ROOT_DIR/scripts/validate_release_compose_metadata.py" \
        --commit "$KM_GIT_COMMIT" \
        --release-id "$KM_RELEASE_ID" \
        --image-digest "$KM_IMAGE_DIGEST" \
        --build-timestamp "$KM_BUILD_TIMESTAMP" \
        <<<"$config_json" || fail "rendered Compose release metadata is invalid or inconsistent"
}

validate_shared_job_ledger_config() {
    local config_json
    config_json="$("${COMPOSE[@]}" --profile scheduler config --format json)" || fail \
        "unable to render Compose JSON for job ledger validation"
    python3 -c '
import json
import sys

config = json.loads(sys.stdin.read())
services = config.get("services", {})
required = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")
paths = {}
for name in required:
    service = services.get(name)
    if not service:
        raise SystemExit(f"job ledger validation: missing service {name}")
    environment = service.get("environment", {})
    path = environment.get("KB_JOB_LEDGER_PATH")
    if not path or not path.startswith("/") or not path.endswith("/job-ledger.sqlite3"):
        raise SystemExit(f"job ledger validation: {name} needs one absolute job ledger path")
    paths[name] = path
if len(set(paths.values())) != 1:
    raise SystemExit(f"job ledger validation: services do not share one path: {paths}")
print(f"Shared job ledger: {next(iter(paths.values()))}")
' <<<"$config_json" || fail "Compose services do not share a valid job ledger path"
}

container_running() {
    [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]
}

show_containers() {
    local failed=0 name
    printf '%-24s %-12s %s\n' "CONTAINER" "STATE" "IMAGE"
    for name in "${APP_CONTAINERS[@]}" kb-redis kb-neo4j kb-report-registry kb-qdrant; do
        if docker inspect "$name" >/dev/null 2>&1; then
            printf '%-24s %-12s %s\n' \
                "$name" \
                "$(docker inspect -f '{{.State.Status}}' "$name")" \
                "$(docker inspect -f '{{.Config.Image}}' "$name")"
            container_running "$name" || failed=1
        else
            printf '%-24s %-12s %s\n' "$name" "missing" "-"
            failed=1
        fi
    done
    return "$failed"
}

http_code() {
    local code
    code="$(curl -k -sS --max-time 10 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)" || code="000"
    printf '%s' "$code"
}

wait_for_http_200() {
    local url="$1" deadline=$((SECONDS + WAIT_TIMEOUT)) code
    while ((SECONDS < deadline)); do
        code="$(http_code "$url")"
        [[ "$code" == "200" ]] && return 0
        sleep 2
    done
    printf 'Timed out waiting for %s (last HTTP %s)\n' "$url" "$code" >&2
    return 1
}

run_bounded_deployment_readiness() {
    local output="$ROOT_DIR/outputs/deployment-readiness/$(date +%Y%m%d-%H%M%S).json"
    local args=(
        --direct-base-url "$DIRECT_BACKEND_URL"
        --ingress-base-url "$BASE_URL"
        --timeout-seconds "$WAIT_TIMEOUT"
        --interval-seconds 2
        --output "$output"
    )
    if [[ -n "${KM_GIT_COMMIT:-}" && -n "${KM_RELEASE_ID:-}" &&
          -n "${KM_IMAGE_DIGEST:-}" && -n "${KM_BUILD_TIMESTAMP:-}" ]]; then
        args+=(
            --expected-commit "$KM_GIT_COMMIT"
            --expected-release-id "$KM_RELEASE_ID"
            --expected-image-digest "$KM_IMAGE_DIGEST"
            --expected-build-timestamp "$KM_BUILD_TIMESTAMP"
        )
    fi
    python3 "$ROOT_DIR/scripts/check_deployment_readiness.py" "${args[@]}"
}

check_wp0_contract() {
    local path code tmp trace
    local failed=0
    trace="restart-gate-$(date +%s)"
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/kb-wp0-gate.XXXXXX")"
    for path in /health /api/v1/health /api/v1/health/live /api/v1/health/ready /api/v1/version; do
        code="$(http_code "$BASE_URL$path")"
        printf '%-32s HTTP %s\n' "$path" "$code"
        [[ "$code" == "200" ]] || failed=1
    done

    code="$(curl -k -sS --max-time 10 -D "$tmp/headers" -o "$tmp/body" -w '%{http_code}' \
        -H "X-Trace-ID: $trace" "$BASE_URL/api/v1/not-found" 2>/dev/null || true)"
    if [[ "$code" == "404" ]] && grep -qi "^x-trace-id: $trace" "$tmp/headers" && \
       python3 - "$tmp/body" "$trace" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload == {
    "data": None,
    "error": {"code": "http_404", "message": "Not Found"},
    "trace_id": sys.argv[2],
}
PY
    then
        printf '%-32s PASS\n' "WP0 error/trace envelope"
    else
        printf '%-32s FAIL\n' "WP0 error/trace envelope"
        failed=1
    fi

    code="$(http_code "$BASE_URL/api/agent/v1/health")"
    printf '%-32s HTTP %s (expected 401)\n' "Agent auth boundary" "$code"
    [[ "$code" == "401" ]] || failed=1
    rm -rf -- "$tmp"
    return "$failed"
}

celery_inspect() {
    docker exec kb-celery-search celery -A src.web_api.tasks.celery_app inspect "$1" 2>&1
}

wait_for_celery_ping() {
    local deadline=$((SECONDS + WAIT_TIMEOUT)) ping
    while ((SECONDS < deadline)); do
        if ping="$(celery_inspect ping 2>/dev/null)" && [[ "$(grep -c 'pong' <<<"$ping")" -ge 2 ]]; then
            printf '%-32s PASS (2 nodes ready)\n' "WP1 Celery readiness"
            return 0
        fi
        sleep 2
    done
    printf '%-32s FAIL (workers did not become ready)\n' "WP1 Celery readiness"
    return 1
}

show_task_activity() {
    local kind output busy=0 queue count
    if ! container_running kb-celery-search || ! container_running kb-redis; then
        printf 'Celery/Redis is not available for task inspection.\n' >&2
        return 2
    fi

    for kind in active reserved scheduled; do
        if ! output="$(celery_inspect "$kind")"; then
            printf 'Celery inspect %s failed.\n' "$kind" >&2
            return 2
        fi
        if grep -qE '^[[:space:]]+\* \{' <<<"$output"; then
            printf '%-12s BUSY\n' "$kind"
            busy=1
        else
            printf '%-12s empty\n' "$kind"
        fi
    done

    for queue in search ingest default document indexing celery; do
        count="$(docker exec kb-redis redis-cli --raw LLEN "$queue" 2>/dev/null || printf 'unknown')"
        printf 'queue:%-6s %s\n' "$queue" "$count"
        [[ "$count" =~ ^[0-9]+$ ]] || return 2
        ((count == 0)) || busy=1
    done
    return "$busy"
}

require_idle_tasks() {
    local task_rc=0
    info "WP1 task drain gate"
    show_task_activity || task_rc=$?
    if ((task_rc == 0)); then
        printf 'Task drain gate: PASS\n'
        return 0
    fi
    case "$task_rc" in
        1) fail "Celery work is active or queued; wait for completion before $MODE" ;;
        *) fail "task state could not be verified; refusing to $MODE" ;;
    esac
}

check_wp1_runtime() {
    local ping queues config beat failed=0
    if ping="$(celery_inspect ping)" && [[ "$(grep -c 'pong' <<<"$ping")" -ge 2 ]]; then
        printf '%-32s PASS (2 nodes)\n' "WP1 Celery ping"
    else
        printf '%-32s FAIL\n' "WP1 Celery ping"
        failed=1
    fi

    if queues="$(celery_inspect active_queues)" && grep -q "'name': 'search'" <<<"$queues" && \
       grep -q "'name': 'ingest'" <<<"$queues"; then
        printf '%-32s PASS\n' "WP1 search/ingest queues"
    else
        printf '%-32s FAIL\n' "WP1 search/ingest queues"
        failed=1
    fi

    if config="$(docker exec kb-web python -c 'from app.core.job_config import JOB_CONFIG; print(JOB_CONFIG)' 2>&1)"; then
        printf '%-32s PASS\n' "WP1 JobConfig"
        printf '  %s\n' "$config"
    else
        printf '%-32s FAIL\n' "WP1 JobConfig"
        failed=1
    fi

    beat="$(docker logs --since "${WAIT_TIMEOUT}s" kb-celery-beat 2>&1 || true)"
    if container_running kb-celery-beat && \
       (docker top kb-celery-beat 2>/dev/null | grep -Eq 'celery.*beat|beat.*celery' || \
        grep -Eq 'beat: Starting|celery beat|Scheduler:' <<<"$beat"); then
        printf '%-32s PASS\n' "WP1 Beat scheduler"
    else
        printf '%-32s FAIL\n' "WP1 Beat scheduler"
        failed=1
    fi
    return "$failed"
}

check_websocket_proxy() {
    local auth_token
    auth_token="$(docker exec kb-web python3 -c \
        "from src.web_api import load_openclaw_chat_config; print(load_openclaw_chat_config().get('authToken', ''))" \
        2>/dev/null | tr -d '\r\n')"
    if [[ -z "$auth_token" ]]; then
        printf '%-32s SKIP (token unavailable)\n' "Legacy WebSocket proxy"
        return 0
    fi
    if docker exec -i kb-web python3 - "$auth_token" <<'PY'
import asyncio, json, ssl, sys
import websockets

async def main():
    context = ssl._create_unverified_context()
    async with websockets.connect("wss://nginx/ws", ssl=context, open_timeout=10) as ws:
        await ws.send(json.dumps({"type": "auth", "token": sys.argv[1]}))
        payload = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if not (payload.get("type") == "event" and payload.get("event") == "connect.challenge"):
            raise RuntimeError(f"unexpected payload: {payload}")

asyncio.run(main())
PY
    then
        printf '%-32s PASS\n' "Legacy WebSocket proxy"
    else
        printf '%-32s FAIL\n' "Legacy WebSocket proxy"
        return 1
    fi
}

run_acceptance_gates() {
    local failed=0
    info "Waiting for WP0 readiness"
    wait_for_http_200 "$BASE_URL/api/v1/health/ready" || failed=1

    info "WP0 compatibility and contract gates"
    check_wp0_contract || failed=1

    info "WP1 worker and scheduler gates"
    wait_for_celery_ping || failed=1
    check_wp1_runtime || failed=1

    info "Legacy compatibility gates"
    [[ "$(http_code "$BASE_URL/chat.html")" == "200" ]] || failed=1
    check_websocket_proxy || failed=1

    local qdrant_code
    qdrant_code="$(http_code 'http://127.0.0.1:6335/healthz')"
    printf '%-32s HTTP %s\n' "Qdrant health" "$qdrant_code"
    [[ "$qdrant_code" == "200" ]] || failed=1
    if curl -fsS --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        printf '%-32s PASS\n' "Host Ollama"
    else
        printf '%-32s FAIL\n' "Host Ollama"
        failed=1
    fi
    ((failed == 0)) || return 1
    printf '\nAll WP0/WP1 acceptance gates: PASS\n'
}

run_status() {
    local failed=0
    info "Knowledge-base runtime status"
    show_containers || failed=1
    run_acceptance_gates || failed=1
    info "Current task activity (read-only)"
    show_task_activity || true
    printf '\nUser entry: %s/chat.html\n' "$EXTERNAL_URL"
    ((failed == 0))
}

build_frontend() {
    local target="$1"
    require_command npm
    case "$target" in
        "$ROOT_DIR"/*) ;;
        *) fail "frontend staging directory must be inside the project root" ;;
    esac
    rm -rf -- "$target"
    KB_FRONTEND_BUILD_DIR="$target" npm --prefix frontend run build
    install -d "$target/lib"
    install -m 0644 frontend/chat.html "$target/chat.html"
    install -m 0644 frontend/lib/marked.min.js "$target/lib/marked.min.js"
    install -m 0644 frontend/lib/compare-rules.js "$target/lib/compare-rules.js"
}

run_restart() {
    compose_preflight
    require_idle_tasks
    info "Restarting application services without rebuild"
    "${COMPOSE[@]}" restart "${APP_SERVICES[@]}"
    run_acceptance_gates || fail "restart completed but WP0/WP1 gates failed"
}

check_deploy_source() {
    local dirty
    dirty="$(git status --porcelain -- . \
        ':!PROJECT_MEMORY.md' ':!config/**' ':!data/**' ':!**/__pycache__/**')"
    if [[ -n "$dirty" && "$ALLOW_DIRTY" != true ]]; then
        printf '%s\n' "$dirty" >&2
        fail "tracked source changes exist; commit them or use --allow-dirty after review"
    fi
}

validate_checkpoint() {
    local checkpoint="$1"
    [[ -f "$checkpoint/checkpoint.json" ]] || fail "checkpoint.json is missing: $checkpoint"
    [[ -f "$checkpoint/SHA256SUMS" ]] || fail "SHA256SUMS is missing: $checkpoint"
    (cd "$checkpoint" && sha256sum -c SHA256SUMS >/dev/null) || fail "checkpoint checksum validation failed"
}

prepare_checkpoint() {
    if [[ -n "$CHECKPOINT" ]]; then
        CHECKPOINT="$(realpath "$CHECKPOINT")"
        validate_checkpoint "$CHECKPOINT"
        printf 'Using verified checkpoint: %s\n' "$CHECKPOINT"
        return 0
    fi
    local label output
    label="pre-deploy-$(date +%Y%m%d-%H%M%S)"
    output="$(python3 scripts/pre_wp01_backup.py \
        --source-root "$ROOT_DIR" --backup-root "$BACKUP_ROOT" --label "$label")"
    CHECKPOINT="$(tail -n 1 <<<"$output")"
    validate_checkpoint "$CHECKPOINT"
    printf 'Created verified checkpoint: %s\n' "$CHECKPOINT"
}

rollback_deploy() {
    printf '\nDeployment gate failed; restoring application images from %s\n' "$CHECKPOINT" >&2
    python3 scripts/rollback_pre_wp01.py \
        --checkpoint "$CHECKPOINT" \
        --execute \
        --confirm-production PRE_WP01_ROLLBACK
}

restore_frontend() {
    local previous="$1"
    rm -rf -- "$FRONTEND_BUILD_DIR"
    if [[ -d "$previous" ]]; then
        mv -- "$previous" "$FRONTEND_BUILD_DIR"
    fi
}

run_deploy() {
    [[ "$CONFIRM_DEPLOY" == "DEPLOY_WP01" ]] || fail \
        "--deploy requires --confirm-deploy DEPLOY_WP01"
    compose_preflight
    check_deploy_source
    require_idle_tasks

    info "Creating or validating rollback checkpoint"
    prepare_checkpoint

    local candidate_id release_tag frontend_staging frontend_previous
    release_tag="$(git rev-parse --short=12 HEAD)-$(date +%Y%m%d%H%M%S)"
    frontend_staging="$ROOT_DIR/.frontend-build-candidate-$release_tag"
    frontend_previous="$ROOT_DIR/.frontend-build-previous-$release_tag"

    info "Building staged frontend and WP0/WP1 candidate image"
    build_frontend "$frontend_staging"
    "${COMPOSE[@]}" build web celery_search_worker celery_ingest_worker celery_beat

    candidate_id="$("${COMPOSE[@]}" images -q web)"
    if [[ -z "$candidate_id" ]]; then
        local built_web_image
        built_web_image="$("${COMPOSE[@]}" config --images | awk '$0 ~ /-web$/ {print; exit}')"
        [[ -n "$built_web_image" ]] || fail "candidate web image name was not produced"
        candidate_id="$(docker image inspect "$built_web_image" --format '{{.Id}}' 2>/dev/null || true)"
    fi
    [[ -n "$candidate_id" ]] || fail "candidate web image was not produced"
    docker image tag "$candidate_id" "kb-wp01-candidate:$release_tag"

    rm -rf -- "$frontend_previous"
    if [[ -d "$FRONTEND_BUILD_DIR" ]]; then
        mv -- "$FRONTEND_BUILD_DIR" "$frontend_previous"
    fi
    mv -- "$frontend_staging" "$FRONTEND_BUILD_DIR"

    info "Recreating application services; data services remain running"
    if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate "${APP_SERVICES[@]}"; then
        restore_frontend "$frontend_previous"
        rollback_deploy
        fail "candidate containers failed to start; rollback completed"
    fi
    if ! run_bounded_deployment_readiness; then
        restore_frontend "$frontend_previous"
        rollback_deploy
        fail "bounded deployment readiness gate failed; rollback completed"
    fi
    if ! run_acceptance_gates; then
        restore_frontend "$frontend_previous"
        rollback_deploy
        fail "candidate failed WP0/WP1 gates; rollback completed"
    fi
    rm -rf -- "$frontend_previous"
    docker image tag "$candidate_id" "kb-wp01-live:$release_tag"
    printf '\nDeployment completed.\nCandidate: kb-wp01-candidate:%s\nLive: kb-wp01-live:%s\nCheckpoint: %s\n' \
        "$release_tag" "$release_tag" "$CHECKPOINT"
}

main() {
    parse_args "$@"
    require_command docker
    require_command curl
    require_command python3

    case "$MODE" in
        status) run_status ;;
        restart) run_restart ;;
        deploy) run_deploy ;;
        *) fail "unsupported mode: $MODE" ;;
    esac
}

main "$@"
