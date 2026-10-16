#!/usr/bin/env bash
# DEV da40 資料區與 Control DB 的 compose 入口：dev-km-plane-compose.sh <da40|control-db> <compose 子指令...>
# 取代已遺失的 /tmp/km-3030-control-cutover-clean。（RD2 已於 2026-10-15 完整移除）
# runtime 副本須與 git 一致；不在 git 的外部檔以 SHA-256 鎖定；變更類指令只允許該組服務且需明確指定；禁止 down。
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
control="${KM_DEV_CONTROL_DIR:-/home/da40_ai_gb10/.km-control}"
overlays="${KM_DEV_COMPOSE_OVERLAY_DIR:-$control/compose}"
csit_pkg="${KM_DEV_DA40_CSIT_PACKAGE_DIR:-$control/csit-post-acceptance-freeze-20261015/rotation-execution-package-20261015}"
target="${1:-}"; shift || true

same_as_git() { cmp -s "$1" "$repo/$2" || { echo "MISMATCH：$1 與 git $2 不同" >&2; exit 3; }; }
pinned() { [ "$(sha256sum "$1" 2>/dev/null | cut -d' ' -f1)" = "$2" ] || { echo "MISMATCH：$1 的 SHA-256 已變更或檔案不存在（外部檔需重新核對）" >&2; exit 3; }; }

zone_services=(web celery_ingest_worker celery_search_worker neo4j qdrant redis report_registry timescaledb)
case "$target" in
  da40)
    project="km-da40"; project_dir="$overlays/tenant-isolation"; env_file="$control/planes/da40.env"
    same_as_git "$project_dir/docker-compose.instance.yml" deploy/tenant-isolation/docker-compose.instance.yml
    # Codex CSIT rotation package（2026-10-15），唯讀引用並鎖定內容
    pinned "$csit_pkg/km-da40-runtime-supplement.yml" eb6218702f2c4fbe632dddb33279b81feccafec1cb8cda4e18e8612f8b9620d0
    pinned "$csit_pkg/km-ui-ddl-free-images.override.yml" f878e1840f78c3267fa475153355948bd5d09ce696152af29f4883ef5e74f200
    files=("$project_dir/docker-compose.instance.yml" "$control/planes/da40.override.yml"
           "$csit_pkg/km-da40-runtime-supplement.yml" "$csit_pkg/km-ui-ddl-free-images.override.yml"
           "$overlays/km-da40.llm-primary.override.yml" "$overlays/km-da40.wifi8.override.yml")
    same_as_git "$overlays/km-da40.llm-primary.override.yml" deploy/dev-3030/compose/km-da40.llm-primary.override.yml
    same_as_git "$overlays/km-da40.wifi8.override.yml" deploy/dev-3030/compose/km-da40.wifi8.override.yml
    allowed=("${zone_services[@]}")
    ;;
  control-db)
    project="km-control-3030"; project_dir="$overlays/legacy-test"; env_file="$control/control-3030.env"
    same_as_git "$project_dir/docker-compose.control-auth.yml" deploy/legacy-test/docker-compose.control-auth.yml
    files=("$project_dir/docker-compose.control-auth.yml" "$control/control-auth.override.yml")
    allowed=(control_db)   # control_auth 由 cross-search-credentials-deploy 的 runtime-compose.json 管理
    ;;
  *) echo "用法：$0 <da40|control-db> <compose 子指令...>" >&2; exit 2 ;;
esac
for f in "${files[@]}" "$env_file"; do [ -r "$f" ] || { echo "缺少檔案：$f" >&2; exit 2; }; done

if [ $# -gt 0 ]; then
  case "$1" in
    up|down|rm|stop|restart|create|start|kill|pull|build)
      [ "$1" = down ] && { echo "禁止使用 down；請用 stop/rm 並指定服務" >&2; exit 4; }
      services=()
      for arg in "${@:2}"; do [[ "$arg" == -* ]] || services+=("$arg"); done
      [ ${#services[@]} -gt 0 ] || { echo "$1 必須明確指定服務：${allowed[*]}" >&2; exit 4; }
      for s in "${services[@]}"; do
        [[ " ${allowed[*]} " == *" $s "* ]] || { echo "不允許的服務：$s（允許：${allowed[*]}）" >&2; exit 4; }
      done
      ;;
  esac
fi

args=(-p "$project" --project-directory "$project_dir" --env-file "$env_file")
for f in "${files[@]}"; do args+=(-f "$f"); done
exec docker compose "${args[@]}" "$@"
