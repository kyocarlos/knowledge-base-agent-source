#!/usr/bin/env bash
# WiFi 專區品質驗證的排程入口（crontab 使用）。
#   daily   ① 檢索、③ 真實回答可信度：不呼叫 LLM
#   weekly  ①②③ 全部：② 會用題庫實際問 Agent（每區約 34～100 次 LLM 呼叫）
# 同時只允許一個執行（flock）；輸出與紀錄在 $KM_WIFI8_QUALITY_ROOT（預設 ~/.km-control/wifi8-quality）。
# 結束碼沿用 wifi8_quality_check.py：0 PASS、3 WARN、1 FAIL、2 參數或執行錯誤。
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUALITY_ROOT="${KM_WIFI8_QUALITY_ROOT:-$HOME/.km-control/wifi8-quality}"
PYTHON="${KM_WIFI8_QUALITY_PYTHON:-python3}"
MODE="${1:-}"
case "$MODE" in
  daily)  LEVELS="retrieval,trust" ;;
  weekly) LEVELS="retrieval,agent,trust" ;;
  *) echo "用法：$0 daily|weekly" >&2; exit 2 ;;
esac
mkdir -p "$QUALITY_ROOT/cron_logs"
exec 9>"$QUALITY_ROOT/quality.lock"
if ! flock -n 9; then
  echo "$(date -Is) 另一個品質驗證正在執行，略過本次 $MODE" >> "$QUALITY_ROOT/cron_logs/skipped.log"
  exit 0
fi
LOG="$QUALITY_ROOT/cron_logs/$(date -u +%Y%m%dT%H%M%SZ)-$MODE.log"
"$PYTHON" "$ROOT_DIR/scripts/wifi8_quality_check.py" --levels "$LEVELS" ${KM_WIFI8_QUALITY_ZONES:+--zones "$KM_WIFI8_QUALITY_ZONES"} > "$LOG" 2>&1
status=$?
echo "$(date -Is) $MODE exit=$status log=$LOG" >> "$QUALITY_ROOT/cron_logs/runs.log"
exit $status
