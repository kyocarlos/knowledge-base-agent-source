#!/usr/bin/env bash
# Put the model menu (frontend/km-llm-select.<hash>.js) on the guide page and the zone assistant pages of the served front end.
#   deploy_llm_select.sh            install (idempotent) and verify
#   deploy_llm_select.sh --verify   verify only (read-only)
#   deploy_llm_select.sh --rollback put every page back as it was before the first install
# Only a <script> tag is added to each page; the pages' own scripts are not touched. The pages are backed up once to $BK as <page>.pre-llm-select.
# Not added to /wifi8/ (the tool-calling agent has no model choice yet), the demo admin page, or the old cpe/smallcell pages.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
RUNTIME=${KM_FRONTEND_RUNTIME:-/srv/knowledge-base-production-rebaseline-20260829-v3/.frontend-build-runtime-user8}
BK=${KM_LLM_SELECT_BACKUP:-/home/da40_ai_gb10/.km-control/llm-select-ui-20261116}
NGINX_CONTAINER=${KM_NGINX_CONTAINER:-kb-nginx}
NGINX_ROOT=${KM_NGINX_ROOT:-/usr/share/nginx/html}
SRC=$(ls "$REPO"/frontend/km-llm-select.*.js | head -1)
JS=$(basename "$SRC")
PAGES=(hub/index.html zones/mobile/index.html zones/broadband/index.html zones/cert/index.html zones/csit/index.html zones/equipment/index.html zones/lab/index.html zones/integrations/index.html)
TAG="<script src=\"/$JS\" defer></script>"
mkdir -p "$BK"

[ "$(sha256sum "$SRC" | cut -c1-12)" = "${JS:14:12}" ] || { echo "FAIL: $JS does not match its content hash"; exit 1; }

install_all() {
  install -m 0664 "$SRC" "$RUNTIME/$JS"
  for p in "${PAGES[@]}"; do
    f="$RUNTIME/$p"
    [ -f "$f" ] || { echo "skip (missing): $p"; continue; }
    mkdir -p "$BK/$(dirname "$p")"
    [ -e "$BK/$p.pre-llm-select" ] || cp -p "$f" "$BK/$p.pre-llm-select"
    if grep -qF "$TAG" "$f"; then echo "already: $p"; continue; fi
    tmp=$(mktemp "$f.XXXXXX")
    # drop an older menu tag (a previous hash), then add the current one just before </body>
    sed -E 's#[[:space:]]*<script src="/km-llm-select\.[0-9a-f]{12}\.js" defer></script>##g' "$f" | python3 -c "
import sys
s = sys.stdin.read()
tag = sys.argv[1]
i = s.rfind('</body>')
if i < 0: sys.exit('no </body> in page')
sys.stdout.write(s[:i] + '  ' + tag + '\n' + s[i:])" "$TAG" > "$tmp"
    chmod --reference="$f" "$tmp"
    mv -f "$tmp" "$f"
    echo "installed: $p"
  done
}

rollback_all() {
  for p in "${PAGES[@]}"; do
    [ -e "$BK/$p.pre-llm-select" ] && cp -p "$BK/$p.pre-llm-select" "$RUNTIME/$p" && echo "restored: $p"
  done
}

verify() {
  local fail=0 want got
  want=$(sha256sum "$SRC" | cut -d' ' -f1)
  got=$(docker exec "$NGINX_CONTAINER" sha256sum "$NGINX_ROOT/$JS" 2>/dev/null | cut -d' ' -f1 || true)
  if [ "$want" = "$got" ]; then echo "PASS nginx serves $JS"; else echo "FAIL nginx $JS expected $want got ${got:-missing}"; fail=1; fi
  for p in "${PAGES[@]}"; do
    if docker exec "$NGINX_CONTAINER" grep -qF "$TAG" "$NGINX_ROOT/$p" 2>/dev/null; then echo "PASS $p has the menu script"; else echo "FAIL $p has no menu script"; fail=1; fi
  done
  return $fail
}

case "${1:-}" in
  --verify) verify ;;
  --rollback) rollback_all; echo "rolled back; the script file $JS stays in place (nothing loads it)" ;;
  *) install_all; verify ;;
esac
