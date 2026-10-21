#!/usr/bin/env bash
# DEV TEST plane（kb-web、kb-celery-ingest、kb-celery-search、kb-nginx）的 compose 入口。
# 固定檔案清單、env 檔與專案目錄，取代已遺失的 /tmp overlay。路徑皆可用環境變數覆寫。
# 會變更容器的子指令必須明確指定服務，且只允許下列服務，避免誤動同一 compose 檔內的 redis、neo4j 等。
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
base="${KM_DEV_BASE_RUNTIME_DIR:-/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-phase1-km001-km014-20260903-090830/runtime}"
control="${KM_DEV_CONTROL_DIR:-/home/da40_ai_gb10/.km-control}"
overlays="${KM_DEV_COMPOSE_OVERLAY_DIR:-$control/compose}"
env_file="${KM_DEV_COMPOSE_ENV_FILE:-$overlays/kb-test.env}"
allowed=(web celery_ingest_worker celery_search_worker nginx)

files=(
  "$base/docker-compose.yml"
  "$base/rollback-images.yml"
  "$control/kb-login.override.yml"
  "$control/planes/test-worker.override.yml"
  "$overlays/kb-test-workers.image.override.yml"
  "$overlays/kb-web.chat-runtime.override.yml"
  "$overlays/kb-test.llm-primary.override.yml"
  "$overlays/kb-test.wifi8.override.yml"
)
for f in "${files[@]}" "$env_file"; do
  [ -r "$f" ] || { echo "缺少檔案：$f" >&2; exit 2; }
done
# runtime overlay 必須與版本控制內容一致
for name in kb-test-workers.image.override.yml kb-web.chat-runtime.override.yml kb-test.llm-primary.override.yml kb-test.wifi8.override.yml; do
  cmp -s "$overlays/$name" "$repo/deploy/dev-3030/compose/$name" || { echo "MISMATCH：$overlays/$name 與 git 版本不同" >&2; exit 3; }
done

if [ $# -gt 0 ]; then
  case "$1" in
    up|down|rm|stop|restart|create|start|kill|pull|build)
      [ "$1" = down ] && { echo "禁止使用 down（會影響同專案其他容器）；請用 stop/rm 並指定服務" >&2; exit 4; }
      services=()
      for arg in "${@:2}"; do [[ "$arg" == -* ]] || services+=("$arg"); done
      [ ${#services[@]} -gt 0 ] || { echo "$1 必須明確指定服務：${allowed[*]}" >&2; exit 4; }
      for s in "${services[@]}"; do
        [[ " ${allowed[*]} " == *" $s "* ]] || { echo "不允許的服務：$s（允許：${allowed[*]}）" >&2; exit 4; }
      done
      ;;
  esac
fi

args=(-p knowledge-base --project-directory "$base" --env-file "$env_file")
for f in "${files[@]}"; do args+=(-f "$f"); done
exec docker compose "${args[@]}" "$@"
