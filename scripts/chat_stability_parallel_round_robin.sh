#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT_DIR/scripts/chat_stability_parallel_runner.js"
BUCKET_RUNNER="$ROOT_DIR/scripts/chat_stability_bucket_run.js"
CATALOG_FILE="${CATALOG_FILE:-$ROOT_DIR/scripts/chat_stability_parallel_catalog.json}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/final_runs/chat_stability_parallel}"
STATE_FILE="$OUTPUT_ROOT/parallel_round_robin_state.json"
LOCK_FILE="$OUTPUT_ROOT/parallel_round_robin.lock"
LOG_DIR="$OUTPUT_ROOT/parallel_round_robin_logs"
BASE_URL="${BASE_URL:-}"
HEADLESS="${HEADLESS:-}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-}"
RETRY_COUNT="${RETRY_COUNT:-}"
QUESTION_DELAY_MS="${QUESTION_DELAY_MS:-}"

mkdir -p "$OUTPUT_ROOT" "$LOG_DIR"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "Another parallel chat stability run is already in progress. Exiting." >&2
    exit 0
  fi
fi

LOG_FILE="$LOG_DIR/$(date +%Y%m%d_%H%M%S)_parallel_round_robin.log"
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
  ensureDir(path.dirname(filePath));
  const tmpPath = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(value, null, 2), 'utf8');
  fs.renameSync(tmpPath, filePath);
}

function toNumberOrUndefined(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

const catalog = readJson(catalogFile);
const pairs = Array.isArray(catalog.pairs) ? catalog.pairs : [];
if (!pairs.length) throw new Error(`No pairs found in catalog: ${catalogFile}`);

let state = { next_index: 0 };
try {
  state = readJson(stateFile);
} catch (_) {}

const currentIndex = Number.isInteger(state.next_index) ? state.next_index : 0;
const normalizedIndex = ((currentIndex % pairs.length) + pairs.length) % pairs.length;
const selected = pairs[normalizedIndex];
const nextIndex = (normalizedIndex + 1) % pairs.length;
writeJsonAtomic(stateFile, {
  next_index: nextIndex,
  last_index: normalizedIndex,
  last_pair_id: selected.id || '',
  updated_at: new Date().toISOString(),
});

const tempDir = fs.mkdtempSync(path.join(outputRoot, '.parallel_round_robin_'));
const tempPairFile = path.join(tempDir, 'pair.json');
const pairFile = {
  base_url: baseUrlOverride || catalog.base_url || 'https://61.216.9.52:3030/chat.html',
  headless: headlessOverride ? headlessOverride !== 'false' : (catalog.headless !== undefined ? Boolean(catalog.headless) : true),
  timeout_seconds: toNumberOrUndefined(timeoutOverride) || Number(catalog.timeout_seconds) || 120,
  retry_count: toNumberOrUndefined(retryOverride) || Number(catalog.retry_count) || 1,
  question_delay_ms: toNumberOrUndefined(questionDelayOverride) || Number(catalog.question_delay_ms) || 1000,
  pairs: [selected],
};
fs.writeFileSync(tempPairFile, JSON.stringify(pairFile, null, 2), 'utf8');

console.log(`[parallel_round_robin] selected_index=${normalizedIndex} next_index=${nextIndex}`);
console.log(`[parallel_round_robin] selected_pair=${selected.id || ''}`);
console.log(`[parallel_round_robin] schedule=${tempPairFile}`);

const runnerResult = spawnSync('node', [
  runnerPath,
  '--pair-file',
  tempPairFile,
  '--output-root',
  outputRoot,
], {
  cwd: path.dirname(path.dirname(runnerPath)),
  stdio: 'inherit',
  env: process.env,
});

try { fs.rmSync(tempDir, { recursive: true, force: true }); } catch (_) {}
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
