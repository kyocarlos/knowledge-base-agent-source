#!/usr/bin/env bash
# 唯讀對帳：以 dev-kb-test-compose.sh（TEST plane）、dev-kb-infra-compose.sh（共用基礎設施）、
# dev-km-plane-compose.sh（da40／rd2 資料區與 Control DB）
# 的檔案組合計算 config-hash，與執行中容器的 com.docker.compose.config-hash 比對。
# 同時檢查映像漂移（標籤已指向新映像但容器仍跑舊映像）。全部一致輸出 MATCH（0），否則 MISMATCH（1）。
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
  dev-kb-infra-compose.sh:kb-timescaledb:timescaledb \
  dev-km-plane-compose.sh@da40:km-da40-web-1:web \
  dev-km-plane-compose.sh@da40:km-da40-celery_ingest_worker-1:celery_ingest_worker \
  dev-km-plane-compose.sh@da40:km-da40-celery_search_worker-1:celery_search_worker \
  dev-km-plane-compose.sh@da40:km-da40-neo4j-1:neo4j \
  dev-km-plane-compose.sh@da40:km-da40-qdrant-1:qdrant \
  dev-km-plane-compose.sh@da40:km-da40-redis-1:redis \
  dev-km-plane-compose.sh@da40:km-da40-report_registry-1:report_registry \
  dev-km-plane-compose.sh@da40:km-da40-timescaledb-1:timescaledb \
  dev-km-plane-compose.sh@rd2:km-rd2-web-1:web \
  dev-km-plane-compose.sh@rd2:km-rd2-celery_ingest_worker-1:celery_ingest_worker \
  dev-km-plane-compose.sh@rd2:km-rd2-celery_search_worker-1:celery_search_worker \
  dev-km-plane-compose.sh@rd2:km-rd2-neo4j-1:neo4j \
  dev-km-plane-compose.sh@rd2:km-rd2-qdrant-1:qdrant \
  dev-km-plane-compose.sh@rd2:km-rd2-redis-1:redis \
  dev-km-plane-compose.sh@rd2:km-rd2-report_registry-1:report_registry \
  dev-km-plane-compose.sh@rd2:km-rd2-timescaledb-1:timescaledb \
  dev-km-plane-compose.sh@control-db:km-control-3030-control_db-1:control_db; do
  IFS=: read -r wrapper container service <<<"$entry"
  target=""; [[ "$wrapper" == *@* ]] && { target="${wrapper#*@}"; wrapper="${wrapper%@*}"; }
  want="$("$here/$wrapper" $target config --hash "$service" 2>/dev/null | awk '{print $2}')"
  have="$(docker inspect "$container" --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' 2>/dev/null)"
  # 標籤可能已被重新 build：容器實際映像須等於標籤目前指向的映像，否則重建會換映像
  running_image="$(docker inspect "$container" --format '{{.Image}}' 2>/dev/null)"
  tag_image="$(docker image inspect "$(docker inspect "$container" --format '{{.Config.Image}}' 2>/dev/null)" --format '{{.Id}}' 2>/dev/null)"
  if [ -z "$want" ] || [ "$want" != "$have" ]; then
    printf '%-32s %-22s compose=%s 容器=%s  設定不一致\n' "$container" "$service" "${want:0:12}" "${have:0:12}"
    status=1
  elif [ "$running_image" != "$tag_image" ]; then
    printf '%-32s %-22s %s  映像漂移（容器=%s 標籤現指=%s）\n' "$container" "$service" "${want:0:12}" "${running_image:7:12}" "${tag_image:7:12}"
    status=1
  else
    printf '%-32s %-22s %s  一致\n' "$container" "$service" "${want:0:12}"
  fi
done
[ $status -eq 0 ] && echo MATCH || echo MISMATCH
exit $status
