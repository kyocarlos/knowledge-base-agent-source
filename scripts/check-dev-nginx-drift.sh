#!/usr/bin/env bash
# 唯讀對帳：版本控制中的 DEV Nginx 設定 vs 主機 runtime 檔 vs 容器實際載入的設定。
# 全部一致輸出 MATCH 並回傳 0；任何不一致或無法讀取輸出 MISMATCH 並回傳 1。
set -uo pipefail
cd "$(dirname "$0")/.."
git_file="${KM_DEV_NGINX_GIT_FILE:-deploy/dev-3030/nginx.runtime.conf}"
host_file="${KM_DEV_NGINX_HOST_FILE:-/home/da40_ai_gb10/.km-control/nginx.runtime.conf}"
container="${KM_DEV_NGINX_CONTAINER:-kb-nginx}"
container_file="${KM_DEV_NGINX_CONTAINER_FILE:-/etc/nginx/nginx.conf}"

sha() { sha256sum | cut -d' ' -f1; }
git_sha="$( [ -r "$git_file" ] && sha < "$git_file" || echo unreadable)"
host_sha="$( [ -r "$host_file" ] && sha < "$host_file" || echo unreadable)"
container_sha="$(docker exec "$container" cat "$container_file" 2>/dev/null | sha)"
[ "$container_sha" = "$(printf '' | sha)" ] && container_sha=unreadable

printf 'git        %s  %s\n' "$git_sha" "$git_file"
printf 'host       %s  %s\n' "$host_sha" "$host_file"
printf 'container  %s  %s:%s\n' "$container_sha" "$container" "$container_file"
if [ "$git_sha" = "$host_sha" ] && [ "$host_sha" = "$container_sha" ] && [ "$git_sha" != unreadable ]; then
  echo MATCH
  exit 0
fi
echo MISMATCH
exit 1
