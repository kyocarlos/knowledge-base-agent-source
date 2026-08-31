#!/usr/bin/env bash
# WP1 production transaction orchestration.  Secrets are read by Compose/runner,
# never printed or copied into evidence.

set -u
set -o pipefail

die() { printf 'FAIL_CLOSED: %s\n' "$1" >&2; exit 1; }
need() { [ -n "${!1:-}" ] || die "missing $1"; }
event() {
    printf '{"event":"%s","execution_mode":"%s","recorded_at":"%s","secrets_included":false}\n' \
        "$1" "$EXECUTION_MODE" "$(date -u +%FT%TZ)" >> "$ORCH_LOG"
}

need WP1_RUN_ID
need WP1_PROD
need WP1_EVIDENCE_ROOT
need WP1_BASE_ENV
need WP1_OVERLAY
need WP1_PINNED_OVERRIDE
need WP1_CREDENTIALS_ENV
need WP1_FIXTURE
need WP1_ATTACHMENT
need WP1_EXPECTED_GIT_HEAD
need WP1_EXPECTED_RUNNER_SHA
need WP1_EXPECTED_CRYPTO_SHA
need WP1_EXPECTED_COMMIT
need WP1_EXPECTED_RELEASE_ID
need WP1_EXPECTED_IMAGE_ID
need WP1_EXPECTED_BUILD_TIMESTAMP

EXECUTION_MODE="${WP1_EXECUTION_MODE:-production}"
case "$EXECUTION_MODE" in
  production|isolated) ;;
  *) die 'execution mode must be production or isolated' ;;
esac

case "$WP1_RUN_ID" in
  TR-E2E-WP1-PROD-*) ;;
  *) die 'run ID does not use the approved production prefix' ;;
esac

SOURCE_ROOT="$WP1_PROD"
TX_DIR="$WP1_EVIDENCE_ROOT/$WP1_RUN_ID"
ORCH_LOG="$TX_DIR/orchestration.jsonl"
RESULT_FILE="$TX_DIR/transaction-result.json"
ACCEPTANCE_FILE="$TX_DIR/acceptance.json"
mkdir -p "$TX_DIR"
chmod 700 "$TX_DIR"

if [ "$EXECUTION_MODE" = production ]; then
    for isolated_key in WP1_COMPOSE_PROJECT WP1_COMPOSE_FILE WP1_ISOLATED_BASE_URL \
        WP1_ISOLATED_DATA_ROOT WP1_ISOLATED_CONFIG_ROOT WP1_ISOLATED_LEDGER_PATH \
        WP1_ISOLATED_CONTAINER_PREFIX WP1_ISOLATED_PORTS; do
        [ -z "${!isolated_key:-}" ] || die "isolated input is not allowed in production mode: $isolated_key"
    done
    WP1_WEB_TARGET="kb-web"
    WP1_INGEST_TARGET="kb-celery-ingest"
    WP1_SEARCH_TARGET="kb-celery-search"
    WP1_BEAT_TARGET="kb-celery-beat"
    WP1_BASE_URL="https://127.0.0.1:3030"
    COMPOSE_PROJECT_ARGS=()
    COMPOSE_FILE_ARGS=(-f "$WP1_PROD/docker-compose.yml" -f "$WP1_PINNED_OVERRIDE")
else
    need WP1_COMPOSE_PROJECT
    need WP1_COMPOSE_FILE
    need WP1_ISOLATED_BASE_URL
    need WP1_ISOLATED_DATA_ROOT
    need WP1_ISOLATED_CONFIG_ROOT
    need WP1_ISOLATED_LEDGER_PATH
    need WP1_ISOLATED_CONTAINER_PREFIX
    need WP1_ISOLATED_PORTS
    case "$WP1_COMPOSE_PROJECT" in knowledge-base|kb|production|prod) die 'isolated project collides with production' ;; esac
    case "$WP1_ISOLATED_CONTAINER_PREFIX" in kb-*|production-*|prod-*) die 'isolated container prefix collides with production' ;; esac
    case "$WP1_ISOLATED_BASE_URL" in https://127.0.0.1:3030|http://127.0.0.1:8000) die 'isolated base URL collides with production' ;; esac
    case "$WP1_ISOLATED_DATA_ROOT:$WP1_ISOLATED_CONFIG_ROOT:$WP1_ISOLATED_LEDGER_PATH" in
        /srv/knowledge-base-production-*:*|*:/srv/knowledge-base-production-*:*|*:*:/srv/knowledge-base-production-*) die 'isolated path points to production' ;;
        */knowledge-base/data:*|*:*/*/knowledge-base/data:*|*:*:*/*/knowledge-base/data/*) die 'isolated path points to production data' ;;
    esac
    [ -r "$WP1_COMPOSE_FILE" ] || die 'isolated Compose file is not readable'
    WP1_WEB_TARGET="${WP1_WEB_TARGET:?missing WP1_WEB_TARGET}"
    WP1_INGEST_TARGET="${WP1_INGEST_TARGET:?missing WP1_INGEST_TARGET}"
    WP1_SEARCH_TARGET="${WP1_SEARCH_TARGET:?missing WP1_SEARCH_TARGET}"
    WP1_BEAT_TARGET="${WP1_BEAT_TARGET:?missing WP1_BEAT_TARGET}"
    WP1_BASE_URL="$WP1_ISOLATED_BASE_URL"
    COMPOSE_PROJECT_ARGS=(--project-name "$WP1_COMPOSE_PROJECT")
    COMPOSE_FILE_ARGS=(-f "$WP1_COMPOSE_FILE" -f "$WP1_PINNED_OVERRIDE")
fi

[ -n "$(git -C "$WP1_PROD" rev-parse --git-dir 2>/dev/null)" ] || die 'production checkout is missing'
[ "$(git -C "$WP1_PROD" rev-parse HEAD)" = "$WP1_EXPECTED_GIT_HEAD" ] || die 'unexpected operational HEAD'
[ -z "$(git -C "$WP1_PROD" status --porcelain)" ] || die 'production worktree is not clean'
[ -r "$WP1_BASE_ENV" ] || die 'baseline env is not readable'
[ -r "$WP1_CREDENTIALS_ENV" ] || die 'credential env is not readable'
[ -r "$WP1_OVERLAY" ] || die 'temporary overlay is not readable'
[ "$(stat -c %a "$WP1_OVERLAY")" = 600 ] || die 'temporary overlay must be mode 0600'
[ -r "$WP1_PINNED_OVERRIDE" ] || die 'pinned override is not readable'
[ -r "$WP1_FIXTURE" ] || die 'fixture is not readable'
[ -r "$WP1_ATTACHMENT" ] || die 'attachment is not readable'

for key in KB_E2E_WRITE_MODE_ENABLED KB_E2E_AGENT_TOKEN_HASHES_JSON \
    KB_E2E_REVIEWER_TOKEN_HASHES_JSON KB_E2E_CLEANUP_ENABLED \
    KB_E2E_CLEANUP_TOKEN_HASHES_JSON KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX; do
    grep -q "^${key}=" "$WP1_OVERLAY" || die "overlay missing $key"
done

COMPOSE_BASE=(docker compose "${COMPOSE_PROJECT_ARGS[@]}" --env-file "$WP1_BASE_ENV" "${COMPOSE_FILE_ARGS[@]}")
COMPOSE_E2E=(docker compose "${COMPOSE_PROJECT_ARGS[@]}" --env-file "$WP1_BASE_ENV" --env-file "$WP1_OVERLAY" "${COMPOSE_FILE_ARGS[@]}")
RUNNER_MODE_ARGS=()
if [ "$EXECUTION_MODE" = production ]; then
    RUNNER_MODE_ARGS=(--production)
fi

inspect_env() {
    docker inspect "$1" --format '{{range .Config.Env}}{{println .}}{{end}}'
}
mode_value() {
    inspect_env "$WP1_WEB_TARGET" | awk -F= '$1=="KB_E2E_WRITE_MODE_ENABLED"{print $2}'
}
has_key() {
    inspect_env "$1" | awk -F= -v wanted="$2" '$1==wanted{found=1} END{exit found ? 0 : 1}'
}
no_e2e_keys() {
    ! inspect_env "$1" | awk -F= '$1 ~ /^KB_E2E_/{found=1} END{exit found ? 0 : 1}'
}
container_exists() {
    docker inspect "$1" >/dev/null 2>&1
}
verify_isolated_container_identity() {
    case "$WP1_WEB_TARGET" in
        "$WP1_COMPOSE_PROJECT"-*) ;;
        *) die 'isolated web target does not belong to the isolated project' ;;
    esac
    compose_project="$(docker inspect "$WP1_WEB_TARGET" --format '{{index .Config.Labels "com.docker.compose.project"}}' 2>/dev/null)"
    [ "$compose_project" = "$WP1_COMPOSE_PROJECT" ] || die 'isolated web target has an unexpected Compose project'
}

READINESS_INTERVAL_SECONDS="${WP1_READINESS_INTERVAL_SECONDS:-1}"
READINESS_TIMEOUT_SECONDS="${WP1_READINESS_TIMEOUT_SECONDS:-60}"
READINESS_CURL_TIMEOUT_SECONDS="${WP1_READINESS_CURL_TIMEOUT_SECONDS:-5}"
case "$READINESS_INTERVAL_SECONDS:$READINESS_TIMEOUT_SECONDS:$READINESS_CURL_TIMEOUT_SECONDS" in
    *[!0-9:]*|:*|*::|*:) die 'readiness timing values must be non-negative integers' ;;
esac
[ "$READINESS_TIMEOUT_SECONDS" -gt 0 ] || die 'readiness timeout must be positive'
[ "$READINESS_CURL_TIMEOUT_SECONDS" -gt 0 ] || die 'readiness curl timeout must be positive'

readiness_event() {
    local first_success_json=null
    [ -n "${5:-}" ] && first_success_json="\"$5\""
    printf '{"event":"%s","execution_mode":"%s","attempt_count":%s,"interval_seconds":%s,"timeout_seconds":%s,"health_status":"%s","version_status":"%s","first_success_at":%s,"last_error":"%s","recorded_at":"%s","secrets_included":false}\n' \
        "$1" "$EXECUTION_MODE" "$2" "$READINESS_INTERVAL_SECONDS" "$READINESS_TIMEOUT_SECONDS" \
        "${3:-unknown}" "${4:-unknown}" "$first_success_json" "${6:-}" "$(date -u +%FT%TZ)" >> "$ORCH_LOG"
}

wait_for_readiness() {
    local phase="$1"
    local started_at attempts=0 health_status=000 version_status=000 last_error=not_started first_success_at=""
    started_at="$(date +%s)"
    event "${phase}_readiness_started"
    while :; do
        attempts=$((attempts + 1))
        health_status="$(curl -sk --max-time "$READINESS_CURL_TIMEOUT_SECONDS" -o /dev/null -w '%{http_code}' "$WP1_BASE_URL/health" 2>/dev/null)" || health_status=000
        version_status="$(curl -sk --max-time "$READINESS_CURL_TIMEOUT_SECONDS" -o /dev/null -w '%{http_code}' "$WP1_BASE_URL/api/v1/version" 2>/dev/null)" || version_status=000
        if [ "$health_status" = 200 ] && [ "$version_status" = 200 ]; then
            first_success_at="$(date -u +%FT%TZ)"
            readiness_event "${phase}_readiness_passed" "$attempts" "$health_status" "$version_status" "$first_success_at" ""
            return 0
        fi
        if [ "$health_status" != 200 ]; then
            last_error="health_status_${health_status}"
        else
            last_error="version_status_${version_status}"
        fi
        if [ $(( $(date +%s) - started_at )) -ge "$READINESS_TIMEOUT_SECONDS" ]; then
            readiness_event "${phase}_readiness_failed" "$attempts" "$health_status" "$version_status" "" "$last_error"
            return 1
        fi
        sleep "$READINESS_INTERVAL_SECONDS"
    done
}

event precondition_start
if [ "$EXECUTION_MODE" = production ]; then
    [ "$(mode_value)" = false ] || die 'baseline write mode is not false'
fi
"${COMPOSE_BASE[@]}" config --quiet || die 'baseline Compose config failed'
event precondition_pass

MUTATION_STARTED=0
ISOLATED_BOOTSTRAPPED=0
ISOLATED_TORN_DOWN=0
RESTORE_RUNNING=0
RESTORE_DONE=0
RUNNER_EXIT=125
RESTORE_EXIT=125

teardown_isolated() {
    [ "$EXECUTION_MODE" = isolated ] || return 0
    [ "$ISOLATED_BOOTSTRAPPED" -eq 1 ] || return 0
    [ "$ISOLATED_TORN_DOWN" -eq 0 ] || return 0
    ISOLATED_TORN_DOWN=1
    event isolated_teardown_started
    "${COMPOSE_BASE[@]}" down --remove-orphans --volumes
    local teardown_rc=$?
    if [ "$teardown_rc" -eq 0 ]; then
        event isolated_teardown_completed
    else
        event isolated_teardown_failed
    fi
    return "$teardown_rc"
}

restore_web() {
    [ "$RESTORE_DONE" -eq 0 ] || return 0
    [ "$RESTORE_RUNNING" -eq 0 ] || return 1
    RESTORE_RUNNING=1
    event restoration_start
    unset KB_E2E_WRITE_MODE_ENABLED KB_E2E_AGENT_TOKEN_HASHES_JSON \
        KB_E2E_REVIEWER_TOKEN_HASHES_JSON KB_E2E_CLEANUP_ENABLED \
        KB_E2E_CLEANUP_TOKEN_HASHES_JSON KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX
    event post_restore_recreate_started
    "${COMPOSE_BASE[@]}" up -d --no-build --no-deps --force-recreate web
    local compose_rc=$?
    if [ "$compose_rc" -eq 0 ] && { [ "$(mode_value)" = false ] || [ -z "$(mode_value)" ]; } && \
        wait_for_readiness post_restore && \
        python3 "$SOURCE_ROOT/scripts/wp1_negative_e2e_probe.py" \
            --base-url "$WP1_BASE_URL" --run-id "$WP1_RUN_ID" \
            --fixture "$WP1_FIXTURE" --attachment "$WP1_ATTACHMENT" \
            --credentials-env "$WP1_CREDENTIALS_ENV" \
            --evidence-out "$TX_DIR/negative-probe.json"; then
        event restoration_verified
        RESTORE_DONE=1
        return 0
    fi
    event restoration_failed
    return 1
}

on_exit() {
    local rc=$?
    if [ "$MUTATION_STARTED" -eq 1 ]; then
        restore_web
        RESTORE_EXIT=$?
        [ "$RESTORE_EXIT" -eq 0 ] || rc=1
    fi
    [ "$MUTATION_STARTED" -eq 1 ] || event no_mutation_restore_required
    [ "$MUTATION_STARTED" -eq 1 ] || RESTORE_EXIT=0
    teardown_isolated
    [ "$?" -eq 0 ] || rc=1
    printf '{"runner_exit":%s,"acceptance_result":"%s","restoration_result":"%s","transaction_result":"%s","secrets_included":false}\n' \
        "$RUNNER_EXIT" "${ACCEPTANCE_RESULT:-NOT_STARTED}" \
        "$([ "$RESTORE_EXIT" -eq 0 ] && echo PASS || echo FAIL_CLOSED)" \
        "$([ "$rc" -eq 0 ] && [ "$RESTORE_EXIT" -eq 0 ] && echo PASS || echo FAIL_CLOSED)" > "$RESULT_FILE"
    if [ "$MUTATION_STARTED" -eq 1 ] && [ "$RESTORE_EXIT" -eq 0 ]; then
        rm -f -- "$WP1_OVERLAY" "$WP1_PINNED_OVERRIDE"
        event temporary_protected_files_removed
    fi
    exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

if [ "$EXECUTION_MODE" = isolated ]; then
    baseline_mode="$(awk -F= '$1=="KB_E2E_WRITE_MODE_ENABLED"{print $2}' "$WP1_BASE_ENV")"
    [ "$baseline_mode" = false ] || die 'isolated baseline env write mode is not false'
    ! grep -q '^KB_E2E_WRITE_MODE_ENABLED=true$' "$WP1_BASE_ENV" || die 'isolated baseline env contains temporary write mode'
    event isolated_baseline_bootstrap_started
    if container_exists "$WP1_WEB_TARGET"; then
        verify_isolated_container_identity
    else
        "${COMPOSE_BASE[@]}" config --quiet || die 'isolated baseline Compose config failed'
        ISOLATED_BOOTSTRAPPED=1
        "${COMPOSE_BASE[@]}" up -d --no-build
        rc=$?
        [ "$rc" -eq 0 ] || die 'isolated baseline bootstrap failed'
        verify_isolated_container_identity
    fi
    event isolated_baseline_bootstrap_completed
    [ "$(mode_value)" = false ] || die 'isolated baseline write mode is not false'
    ! has_key "$WP1_WEB_TARGET" KB_E2E_AGENT_TOKEN_HASHES_JSON || die 'isolated baseline has temporary agent mapping'
    ! has_key "$WP1_WEB_TARGET" KB_E2E_REVIEWER_TOKEN_HASHES_JSON || die 'isolated baseline has temporary reviewer mapping'
    ! has_key "$WP1_WEB_TARGET" KB_E2E_CLEANUP_TOKEN_HASHES_JSON || die 'isolated baseline has temporary cleanup mapping'
    wait_for_readiness isolated_baseline || die 'isolated baseline readiness failed'
    event isolated_baseline_readiness_passed
    event isolated_baseline_verified
fi

event enablement_start
MUTATION_STARTED=1
event post_enable_recreate_started
"${COMPOSE_E2E[@]}" up -d --no-build --no-deps --force-recreate web
rc=$?
[ "$rc" -eq 0 ] || exit 1

[ "$(mode_value)" = true ] || exit 1
for key in KB_E2E_WRITE_MODE_ENABLED KB_E2E_AGENT_TOKEN_HASHES_JSON \
    KB_E2E_REVIEWER_TOKEN_HASHES_JSON KB_E2E_CLEANUP_ENABLED \
    KB_E2E_CLEANUP_TOKEN_HASHES_JSON KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX; do
    has_key "$WP1_WEB_TARGET" "$key" || exit 1
done
for key in KB_E2E_AGENT_TOKEN_HASHES_JSON KB_E2E_REVIEWER_TOKEN_HASHES_JSON \
    KB_E2E_CLEANUP_ENABLED KB_E2E_CLEANUP_TOKEN_HASHES_JSON \
    KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX; do
    has_key "$WP1_INGEST_TARGET" "$key" || exit 1
done
no_e2e_keys "$WP1_SEARCH_TARGET" || exit 1
no_e2e_keys "$WP1_BEAT_TARGET" || exit 1
wait_for_readiness post_enable || exit 1
event enablement_verified

EVIDENCE_DIR="$TX_DIR"
export PYTHONPATH="$SOURCE_ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
event runner_launch
python3 "$SOURCE_ROOT/scripts/wp1_maintenance_entrypoint.py" \
    --evidence-file "$TX_DIR/wrapper-result.json" \
    --orchestration-log "$ORCH_LOG" \
    -- python3 "$SOURCE_ROOT/scripts/run_wp1_production_acceptance.py" \
    --base-url "$WP1_BASE_URL" \
    --run-id "$WP1_RUN_ID" \
    --fixture "$WP1_FIXTURE" \
    --attachment "$WP1_ATTACHMENT" \
    --credentials-env "$WP1_CREDENTIALS_ENV" \
    --production-evidence-root "$WP1_EVIDENCE_ROOT" \
    --source-root "$SOURCE_ROOT" \
    --expected-git-head "$WP1_EXPECTED_GIT_HEAD" \
    --expected-runner-sha256 "$WP1_EXPECTED_RUNNER_SHA" \
    --expected-crypto-sha256 "$WP1_EXPECTED_CRYPTO_SHA" \
    --expected-commit "$WP1_EXPECTED_COMMIT" \
    --expected-release-id "$WP1_EXPECTED_RELEASE_ID" \
    --expected-image-id "$WP1_EXPECTED_IMAGE_ID" \
    --expected-build-timestamp "$WP1_EXPECTED_BUILD_TIMESTAMP" \
    --evidence-out "$ACCEPTANCE_FILE" \
    "${RUNNER_MODE_ARGS[@]}"
RUNNER_EXIT=$?
if [ "$RUNNER_EXIT" -eq 0 ]; then ACCEPTANCE_RESULT=PASS; else ACCEPTANCE_RESULT=FAIL_CLOSED; fi
event runner_complete
exit "$RUNNER_EXIT"
