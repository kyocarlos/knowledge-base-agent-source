#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/chat_stability_runner.js"
BUCKET_RUNNER="$ROOT_DIR/scripts/chat_stability_bucket_run.js"
SCHEDULE_FILE="${SCHEDULE_FILE:-$ROOT_DIR/scripts/chat_stability_schedule.example.json}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/final_runs/chat_stability}"
BASE_URL="${BASE_URL:-https://61.216.9.52:3030/chat.html}"
HEADLESS="${HEADLESS:-true}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-120}"
RETRY_COUNT="${RETRY_COUNT:-2}"
QUESTION_DELAY_MS="${QUESTION_DELAY_MS:-1000}"
SLOT="${1:-${SLOT:-}}"
LOG_DIR="$OUTPUT_ROOT/cron_logs"
LOCK_FILE="$OUTPUT_ROOT/chat_stability.lock"

mkdir -p "$OUTPUT_ROOT" "$LOG_DIR"

if [[ -z "$SLOT" && "${RUN_ALL:-false}" != "true" ]]; then
  echo "Usage: $0 <slot_id> | RUN_ALL=true $0" >&2
  echo "Example slots: s1_morning, s2_noon, s3_evening, s4_night" >&2
  exit 1
fi

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "Another chat stability run is already in progress. Exiting." >&2
    exit 0
  fi
fi

TS="$(date +%Y%m%d_%H%M%S)"
if [[ -n "$SLOT" ]]; then
  LOG_FILE="$LOG_DIR/${TS}_${SLOT}.log"
else
  LOG_FILE="$LOG_DIR/${TS}_all.log"
fi

{
  echo "[$(date -Iseconds)] root=$ROOT_DIR"
  echo "[$(date -Iseconds)] schedule_file=$SCHEDULE_FILE"
  echo "[$(date -Iseconds)] output_root=$OUTPUT_ROOT"
  echo "[$(date -Iseconds)] base_url=$BASE_URL"
  echo "[$(date -Iseconds)] headless=$HEADLESS timeout_seconds=$TIMEOUT_SECONDS retry_count=$RETRY_COUNT question_delay_ms=$QUESTION_DELAY_MS"
  if [[ -n "$SLOT" ]]; then
    echo "[$(date -Iseconds)] slot=$SLOT"
  else
    echo "[$(date -Iseconds)] slot=ALL"
  fi
} >> "$LOG_FILE"

ARGS=(
  --schedule-file "$SCHEDULE_FILE"
  --output-root "$OUTPUT_ROOT"
  --base-url "$BASE_URL"
  --headless "$HEADLESS"
  --timeout-seconds "$TIMEOUT_SECONDS"
  --retry-count "$RETRY_COUNT"
  --question-delay-ms "$QUESTION_DELAY_MS"
)

if [[ -n "$SLOT" ]]; then
  ARGS+=(--slot "$SLOT")
else
  ARGS+=(--all)
fi

set +e
(
  cd "$ROOT_DIR"
  node "$RUNNER" "${ARGS[@]}"
) 2>&1 | tee -a "$LOG_FILE"
RUNNER_STATUS=${PIPESTATUS[0]}
set -e

BUCKET_STATUS=0
if [[ -d "$OUTPUT_ROOT" ]]; then
  set +e
  node "$BUCKET_RUNNER" --output-root "$OUTPUT_ROOT" 2>&1 | tee -a "$LOG_FILE"
  BUCKET_STATUS=${PIPESTATUS[0]}
  set -e
fi

if [[ $RUNNER_STATUS -ne 0 ]]; then
  exit $RUNNER_STATUS
fi

exit $BUCKET_STATUS
