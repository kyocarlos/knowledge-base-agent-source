#!/usr/bin/env bash
# 唯讀對帳：以 dev-kb-test-compose.sh 的檔案組合計算 config-hash，與執行中容器的
# com.docker.compose.config-hash 比對。全部一致輸出 MATCH（0），否則 MISMATCH（1）。
set -uo pipefail
here="$(dirname "$0")"
status=0
for pair in kb-web:web kb-celery-ingest:celery_ingest_worker kb-celery-search:celery_search_worker kb-nginx:nginx; do
  container="${pair%%:*}"; service="${pair#*:}"
  want="$("$here/dev-kb-test-compose.sh" config --hash "$service" 2>/dev/null | awk '{print $2}')"
  have="$(docker inspect "$container" --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' 2>/dev/null)"
  if [ -n "$want" ] && [ "$want" = "$have" ]; then
    printf '%-18s %-22s %s  一致\n' "$container" "$service" "${want:0:12}"
  else
    printf '%-18s %-22s compose=%s 容器=%s  不一致\n' "$container" "$service" "${want:0:12}" "${have:0:12}"
    status=1
  fi
done
[ $status -eq 0 ] && echo MATCH || echo MISMATCH
exit $status
