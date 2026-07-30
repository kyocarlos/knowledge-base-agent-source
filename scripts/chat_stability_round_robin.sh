#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/chat_stability_runner.js"
BUCKET_RUNNER="$ROOT_DIR/scripts/chat_stability_bucket_run.js"
CATALOG_FILE="${CATALOG_FILE:-$ROOT_DIR/scripts/chat_stability_round_robin_catalog.json}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/final_runs/chat_stability_round_robin}"
LOCK_FILE="$OUTPUT_ROOT/round_robin.lock"
STATE_FILE="$OUTPUT_ROOT/round_robin_state.json"
LOG_DIR="$OUTPUT_ROOT/round_robin_logs"
BASE_URL="${BASE_URL:-}"
HEADLESS="${HEADLESS:-}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-}"
RETRY_COUNT="${RETRY_COUNT:-}"
QUESTION_DELAY_MS="${QUESTION_DELAY_MS:-}"

mkdir -p "$OUTPUT_ROOT" "$LOG_DIR"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "Another round-robin chat stability run is already in progress. Exiting." >&2
    exit 0
  fi
fi

LOG_FILE="$LOG_DIR/$(date +%Y%m%d_%H%M%S)_round_robin.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date -Iseconds)] log_file=$LOG_FILE"
echo "[$(date -Iseconds)] output_root=$OUTPUT_ROOT"
echo "[$(date -Iseconds)] catalog_file=$CATALOG_FILE"
echo "[$(date -Iseconds)] state_file=$STATE_FILE"

set +e
node - "$CATALOG_FILE" "$STATE_FILE" "$RUNNER" "$OUTPUT_ROOT" "$BASE_URL" "$HEADLESS" "$TIMEOUT_SECONDS" "$RETRY_COUNT" "$QUESTION_DELAY_MS" <<'NODE'
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const [
  catalogFile,
  stateFile,
  runnerPath,
  outputRoot,
  baseUrlOverride,
  headlessOverride,
  timeoutOverride,
  retryOverride,
  questionDelayOverride,
] = process.argv.slice(2);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function writeJsonAtomic(filePath, value) {
  const dir = path.dirname(filePath);
  ensureDir(dir);
  const tmpPath = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(value, null, 2), 'utf8');
  fs.renameSync(tmpPath, filePath);
}

function toNumberOrUndefined(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const catalog = readJson(catalogFile);
const questions = Array.isArray(catalog.questions) ? catalog.questions : [];
if (!questions.length) {
  throw new Error(`No questions found in catalog: ${catalogFile}`);
}

let state = { next_index: 0 };
try {
  state = readJson(stateFile);
} catch (_) {}

const currentIndex = Number.isInteger(state.next_index) ? state.next_index : 0;
const normalizedIndex = ((currentIndex % questions.length) + questions.length) % questions.length;
const selected = questions[normalizedIndex];
const nextIndex = (normalizedIndex + 1) % questions.length;
writeJsonAtomic(stateFile, {
  next_index: nextIndex,
  last_index: normalizedIndex,
  last_question_id: selected.id || '',
  last_group: selected.group || '',
  updated_at: new Date().toISOString(),
});

const tempDir = fs.mkdtempSync(path.join(outputRoot, '.round_robin_'));
const tempScheduleFile = path.join(tempDir, 'schedule.json');
const schedule = {
  base_url: baseUrlOverride || catalog.base_url || 'https://127.0.0.1:3030/chat.html',
  headless: headlessOverride ? headlessOverride !== 'false' : (catalog.headless !== undefined ? Boolean(catalog.headless) : true),
  timeout_seconds: toNumberOrUndefined(timeoutOverride) || Number(catalog.timeout_seconds) || 120,
  retry_count: toNumberOrUndefined(retryOverride) || Number(catalog.retry_count) || 2,
  question_delay_ms: toNumberOrUndefined(questionDelayOverride) || Number(catalog.question_delay_ms) || 1000,
  slots: [
    {
      id: 'round_robin',
      label: `Round robin ${selected.group || ''}`.trim(),
      cron: '*/5 * * * *',
      questions: [
        {
          id: selected.id || `question_${normalizedIndex + 1}`,
          text: selected.text,
        },
      ],
    },
  ],
};
fs.writeFileSync(tempScheduleFile, JSON.stringify(schedule, null, 2), 'utf8');

console.log(`[round_robin] selected_index=${normalizedIndex} next_index=${nextIndex}`);
console.log(`[round_robin] selected_group=${selected.group || ''}`);
console.log(`[round_robin] selected_question=${selected.id || ''}`);
console.log(`[round_robin] schedule=${tempScheduleFile}`);

const args = [
  runnerPath,
  '--schedule-file',
  tempScheduleFile,
  '--output-root',
  outputRoot,
];

const runnerResult = spawnSync('node', args, {
  cwd: path.dirname(path.dirname(runnerPath)),
  stdio: 'inherit',
  env: process.env,
});

try {
  fs.rmSync(tempDir, { recursive: true, force: true });
} catch (_) {}

process.exit(runnerResult.status === null ? 1 : runnerResult.status);
NODE
NODE_STATUS=$?
set -e

BUCKET_STATUS=0
if [[ -d "$OUTPUT_ROOT" ]]; then
  set +e
  node "$BUCKET_RUNNER" --output-root "$OUTPUT_ROOT" 2>&1 | tee -a "$LOG_FILE"
  BUCKET_STATUS=${PIPESTATUS[0]}
  set -e
fi

if [[ $NODE_STATUS -ne 0 ]]; then
  exit $NODE_STATUS
fi

exit $BUCKET_STATUS
