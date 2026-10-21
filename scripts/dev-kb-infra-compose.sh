#!/usr/bin/env bash
# DEV 共用基礎設施（kb-redis、kb-report-registry、kb-timescaledb）的 compose 入口。
# 取代已遺失的 /tmp/km-v26-ci-cd-20260915-main-r2 與 /tmp/phase1-timescaledb-infrastructure-override.yml。
# 資料在 knowledge-base_* 具名 volume。會變更容器的子指令必須明確指定服務且只允許下列服務；禁止 down。
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
control="${KM_DEV_CONTROL_DIR:-/home/da40_ai_gb10/.km-control}"
overlays="${KM_DEV_COMPOSE_OVERLAY_DIR:-$control/compose}"
env_file="${KM_DEV_INFRA_ENV_FILE:-/home/da40_ai_gb10/.config/knowledge-base/wp01-deployment.env}"
allowed=(redis report_registry timescaledb)
names=(kb-redis-registry.compose.yml kb-timescaledb.compose.yml)

for name in "${names[@]}"; do
  [ -r "$overlays/$name" ] || { echo "缺少檔案：$overlays/$name" >&2; exit 2; }
  cmp -s "$overlays/$name" "$repo/deploy/dev-3030/compose/$name" || { echo "MISMATCH：$overlays/$name 與 git 版本不同" >&2; exit 3; }
done
[ -r "$env_file" ] || { echo "缺少 env 檔：$env_file" >&2; exit 2; }

if [ $# -gt 0 ]; then
  case "$1" in
    up|down|rm|stop|restart|create|start|kill|pull|build)
      [ "$1" = down ] && { echo "禁止使用 down（會影響同專案其他容器與 volume）；請用 stop/rm 並指定服務" >&2; exit 4; }
      services=()
      for arg in "${@:2}"; do [[ "$arg" == -* ]] || services+=("$arg"); done
      [ ${#services[@]} -gt 0 ] || { echo "$1 必須明確指定服務：${allowed[*]}" >&2; exit 4; }
      for s in "${services[@]}"; do
        [[ " ${allowed[*]} " == *" $s "* ]] || { echo "不允許的服務：$s（允許：${allowed[*]}）" >&2; exit 4; }
      done
      ;;
  esac
fi

args=(-p knowledge-base --project-directory "$overlays" --env-file "$env_file")
for name in "${names[@]}"; do args+=(-f "$overlays/$name"); done
exec docker compose "${args[@]}" "$@"
