#!/usr/bin/env bash
# 部署／對帳 WiFi 專區 SPA 靜態檔（frontend/wifi8）到 DEV Nginx 掛載目錄（TEST、DA40 共用）。
# 用法：scripts/deploy-wifi8-static.sh [--verify] [COMMIT]   （COMMIT 預設 HEAD）
#   部署：只新增 index.html 引用的 hash 檔名 JS/CSS，再原子替換 index.html；舊檔保留，部署前備份 runtime index.html。
#   --verify：唯讀對帳 git(COMMIT) vs 主機目錄 vs 容器實際提供的檔案，並確認未登入請求 302 轉向登入頁。
# 全部一致輸出 VERIFY PASS 並回傳 0；任何不一致輸出 FAIL／MISMATCH 並回傳 1。登入後畫面需另以 Webwright 驗證。
set -euo pipefail
cd "$(dirname "$0")/.."
host_dir="${KM_WIFI8_STATIC_DIR:-/srv/knowledge-base-production-rebaseline-20260829-v3/.frontend-build-runtime-user8/wifi8}"
container="${KM_DEV_NGINX_CONTAINER:-kb-nginx}"
container_dir="${KM_WIFI8_STATIC_CONTAINER_DIR:-/usr/share/nginx/html/wifi8}"
base_url="${KM_BASE_URL:-https://61.216.9.52:3030}"
backup_dir="${KM_WIFI8_STATIC_BACKUP_DIR:-$HOME/.km-control/wifi8-static-backups}"
src_dir=frontend/wifi8

mode=deploy
if [ "${1:-}" = "--verify" ]; then mode=verify; shift; fi
commit="$(git rev-parse --verify "${1:-HEAD}^{commit}")"

stage="$(mktemp -d)"; trap 'rm -rf "$stage"' EXIT
git show "$commit:$src_dir/index.html" > "$stage/index.html"
mapfile -t assets < <(grep -o 'wifi8\.[0-9a-f]\{12\}\.\(js\|css\)' "$stage/index.html" | sort -u)
[ "${#assets[@]}" -gt 0 ] || { echo "FAIL: $commit 的 index.html 沒有引用 hash 檔名的 JS/CSS"; exit 1; }
for f in "${assets[@]}"; do
  git show "$commit:$src_dir/$f" > "$stage/$f"
  [ "$(sha256sum "$stage/$f" | cut -c1-12)" = "$(cut -d. -f2 <<< "$f")" ] || { echo "FAIL: $f 內容與檔名 hash 不符"; exit 1; }
done
files=(index.html "${assets[@]}")
echo "commit $commit：${files[*]}"

deploy() {
  local runtime_blob known
  if cmp -s "$host_dir/index.html" "$stage/index.html"; then
    echo "runtime index.html 已是此版本，只補齊 JS/CSS"
  else
    # runtime index.html 必須是 git 歷史中出現過的版本，否則視為手動修改（MISMATCH）
    runtime_blob="$(git hash-object "$host_dir/index.html")"
    known="$(git log --format=%H -- "$src_dir/index.html" | while read -r c; do
      [ "$(git rev-parse -q --verify "$c:$src_dir/index.html" 2>/dev/null)" = "$runtime_blob" ] && { echo "$c"; break; }; done || true)"
    [ -n "$known" ] || { echo "MISMATCH: runtime index.html（blob $runtime_blob）不在 git 歷史中，停止"; exit 1; }
    mkdir -p "$backup_dir"
    cp -p "$host_dir/index.html" "$backup_dir/index.html.$(date -u +%Y%m%dT%H%M%SZ).${known:0:7}"
    echo "已備份 runtime index.html（來自 ${known:0:7}）到 $backup_dir"
  fi
  for f in "${assets[@]}"; do install -m 0664 "$stage/$f" "$host_dir/$f"; done
  install -m 0664 "$stage/index.html" "$host_dir/.index.html.new" && mv -f "$host_dir/.index.html.new" "$host_dir/index.html"
}

verify() {
  local fail=0 f want host got code location
  for f in "${files[@]}"; do
    want="$(sha256sum < "$stage/$f" | cut -d' ' -f1)"
    host="$( [ -r "$host_dir/$f" ] && sha256sum < "$host_dir/$f" | cut -d' ' -f1 || echo unreadable)"
    got="$(docker exec "$container" sha256sum "$container_dir/$f" 2>/dev/null | cut -d' ' -f1 || true)"
    if [ "$want" = "$host" ] && [ "$want" = "$got" ]; then echo "PASS $f sha256=$want"
    else echo "FAIL $f git=$want host=$host container=${got:-unreadable}"; fail=1; fi
  done
  # /wifi8/ 需登入：未登入請求應 302 轉向 login.html（入口閘道仍生效）
  for f in "" "${assets[@]}"; do
    read -r code location < <(curl -sk -o /dev/null -w '%{http_code} %{redirect_url}\n' "$base_url/wifi8/$f")
    if [ "$code" = 302 ] && [[ "${location:-}" == */login.html* ]]; then echo "PASS 未登入 /wifi8/$f → 302 登入頁"
    else echo "FAIL 未登入 /wifi8/$f 回應 $code ${location:-}（預期 302 → login.html）"; fail=1; fi
  done
  return $fail
}

[ "$mode" = deploy ] && deploy
if verify; then echo "VERIFY PASS"; else echo "VERIFY FAIL"; exit 1; fi
