#!/usr/bin/env bash
# 唯讀對帳：以 dev-kb-test-compose.sh（TEST plane）與 dev-kb-infra-compose.sh（共用基礎設施）
# 的檔案組合計算 config-hash，與執行中容器的 com.docker.compose.config-hash 比對。
# 全部一致輸出 MATCH（0），否則 MISMATCH（1）。
set -uo pipefail
here="$(dirname "$0")"
status=0
for entry in \
  dev-kb-test-compose.sh:kb-web:web \
  dev-kb-test-compose.sh:kb-celery-ingest:celery_ingest_worker \
  dev-kb-test-compose.sh:kb-celery-search:celery_search_worker \
  dev-kb-test-compose.sh:kb-nginx:nginx \
  dev-kb-infra-compose.sh:kb-redis:redis \
  dev-kb-infra-compose.sh:kb-report-registry:report_registry \
  dev-kb-infra-compose.sh:kb-timescaledb:timescaledb; do
  IFS=: read -r wrapper container service <<<"$entry"
  want="$("$here/$wrapper" config --hash "$service" 2>/dev/null | awk '{print $2}')"
  have="$(docker inspect "$container" --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' 2>/dev/null)"
  if [ -n "$want" ] && [ "$want" = "$have" ]; then
    printf '%-20s %-22s %s  一致\n' "$container" "$service" "${want:0:12}"
  else
    printf '%-20s %-22s compose=%s 容器=%s  不一致\n' "$container" "$service" "${want:0:12}" "${have:0:12}"
    status=1
  fi
done
[ $status -eq 0 ] && echo MATCH || echo MISMATCH
exit $status
