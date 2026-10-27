#!/bin/sh
# WiFi 專區「Wi-Fi 8 動態週報」每週排程（主機 cron 執行）。
#
# 1. 在 TEST 區的搜尋 worker 內讀取各來源並產生週報（python -m src.wifi8.digest run；來源見 src/wifi8/digest_sources.json）。
# 2. 把同一份 latest.json 複製到 DA40 區，兩區顯示一致（週報由外部資料產生，不依各區資料；文件更新動態則由各區自己的資料包比對）。
# 3. 失敗或有來源讀取失敗時，用既有的 WiFi 品質驗證通知（Telegram）送一則只含狀態的訊息，不含週報內容。
#
# cron 範例（每週一 08:00，主機時區 Asia/Taipei）：
#   0 8 * * 1 /bin/sh /home/da40_ai_gb10/.km-control/digest/wifi8_digest_cron.sh >> /home/da40_ai_gb10/.km-control/digest/cron.log 2>&1
# 環境變數（可選）：KM_DIGEST_TEST_WORKER、KM_DIGEST_DA40_WORKER、KM_DIGEST_NOTIFY。不含任何 secret。
set -u

TEST_WORKER="${KM_DIGEST_TEST_WORKER:-kb-celery-search}"
DA40_WORKER="${KM_DIGEST_DA40_WORKER:-km-da40-celery_search_worker-1}"
NOTIFY="${KM_DIGEST_NOTIFY:-$HOME/.km-control/cross-search-credentials-20261015/scripts/wifi8_quality_notify.py}"
STAMP="$(date '+%F %T')"

notify() {
  [ -f "$NOTIFY" ] && python3 "$NOTIFY" --text "WiFi 動態週報：$1" >/dev/null 2>&1
  return 0
}
fail() {
  echo "$STAMP FAIL: $1"
  notify "$1"
  exit 1
}

out="$(docker exec "$TEST_WORKER" python -W ignore -m src.wifi8.digest run 2>&1)"
status=$?
last="$(printf '%s\n' "$out" | tail -n 1)"
echo "$STAMP run exit=$status $last"
[ "$status" -eq 0 ] || fail "所有來源都讀取失敗或執行錯誤（保留上次週報）"

tmp="$(mktemp -d)" || fail "無法建立暫存目錄"
trap 'rm -rf "$tmp"' EXIT
docker cp "$TEST_WORKER:/app/data/wifi8/digest/latest.json" "$tmp/latest.json" || fail "讀不到 TEST 區產生的週報"
week="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['week'])" "$tmp/latest.json")" || fail "週報檔格式錯誤"
docker exec "$DA40_WORKER" mkdir -p /app/data/wifi8/digest/archive || fail "DA40 區無法建立週報目錄"
docker cp "$tmp/latest.json" "$DA40_WORKER:/app/data/wifi8/digest/latest.json" || fail "複製週報到 DA40 區失敗"
docker cp "$tmp/latest.json" "$DA40_WORKER:/app/data/wifi8/digest/archive/$week.json" || fail "複製週報存檔到 DA40 區失敗"

failed="$(python3 -c "import json,sys; print(','.join(json.loads(sys.argv[1]).get('sources_failed', [])))" "$last" 2>/dev/null)"
[ -z "$failed" ] || notify "部分來源讀取失敗：$failed（其餘來源已更新）"
echo "$STAMP done week=$week failed_sources=${failed:-none}"
