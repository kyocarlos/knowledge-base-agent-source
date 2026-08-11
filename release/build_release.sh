#!/usr/bin/env bash
set -euo pipefail

IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RELEASE_ROOT="$SCRIPT_DIR"
BUILD_ROOT="$RELEASE_ROOT/.build"
DIST_ROOT="$RELEASE_ROOT/dist"

git_sha="$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
stamp="$(date +%Y%m%d_%H%M%S)"
package_format_version="${KB_RELEASE_FORMAT_VERSION:-1}"
release_version="${KB_RELEASE_VERSION:-${stamp}-${git_sha}}"
release_channel="${KB_RELEASE_CHANNEL:-onprem}"
release_id="${KB_RELEASE_ID:-${release_version}}"

STAGE_ROOT="$BUILD_ROOT/knowledge-base-onprem-$release_id"
APP_DIR="$STAGE_ROOT/app"
RUNTIME_DIR="$STAGE_ROOT/runtime"
DATA_DIR="$STAGE_ROOT/data"
CONFIG_DIR="$APP_DIR/config"
PACKAGE_NAME="knowledge-base-onprem-$release_id.tar.gz"
PACKAGE_PATH="$DIST_ROOT/$PACKAGE_NAME"
CHECKSUM_PATH="$DIST_ROOT/$PACKAGE_NAME.sha256"

log() {
  printf '[release] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[release] missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

copy_source_dir() {
  local source="$1"
  local target="$2"
  if [[ ! -e "$PROJECT_ROOT/$source" ]]; then
    return 0
  fi
  cp -a "$PROJECT_ROOT/$source" "$target/"
}

clean_release_artifacts() {
  rm -rf \
    "$APP_DIR/frontend/node_modules" \
    "$APP_DIR/frontend/build" \
    "$APP_DIR/frontend/build2" \
    "$APP_DIR/frontend/dist" \
    "$APP_DIR/frontend/.vite" \
    "$APP_DIR/frontend/.frontend-build-runtime-user" \
    "$APP_DIR/frontend/.frontend-build-runtime-user8"

  rm -f \
    "$APP_DIR/src/extract_entities.py.bak" \
    "$APP_DIR/src/web_api/tasks.py.bak" \
    "$APP_DIR/frontend/chat_draft"*.html \
    "$APP_DIR/frontend/ws-chat"*.cjs

  find "$APP_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  find "$APP_DIR" -name '*.pyc' -delete
}

write_manifest() {
  cat > "$STAGE_ROOT/manifest.json" <<EOF
{
  "format_version": "$package_format_version",
  "release_id": "$release_id",
  "release_version": "$release_version",
  "release_channel": "$release_channel",
  "git_commit": "$git_sha",
  "created_at": "$stamp",
  "package_name": "$PACKAGE_NAME",
  "layout": {
    "app": "release app copy",
    "runtime": "docker compose, image build files, TLS certs, OpenClaw overlay, frontend runtime",
    "data": "empty runtime data root"
  }
}
EOF
}

write_package_release_info() {
  cat > "$STAGE_ROOT/release-info.json" <<EOF
{
  "format_version": "$package_format_version",
  "release_id": "$release_id",
  "release_version": "$release_version",
  "release_channel": "$release_channel",
  "git_commit": "$git_sha",
  "created_at": "$stamp",
  "package_name": "$PACKAGE_NAME"
}
EOF
}

write_readme() {
  cat > "$STAGE_ROOT/README.md" <<EOF
# Knowledge Base On-Prem Release

Release ID: \`$release_id\`
Git commit: \`$git_sha\`

## Contents

- \`app/\`: isolated application copy used by this release
- \`runtime/\`: Docker Compose, Dockerfile, frontend runtime, TLS certs, OpenClaw overlay
- \`install.sh\`: installer for the on-prem package
- \`manifest.json\`: build metadata

## Install

1. Extract this archive to a local folder.
2. Run \`./install.sh\`.
3. If needed, pass custom values for:
   - install root
   - HTTPS port
   - Ollama base URL
   - OpenClaw overlay / session key
   - optional data bundle

The installer uses safer chat defaults for new installs and upgrades:

- KB_CHAT_GLOBAL_CONCURRENCY_LIMIT=2
- KB_CHAT_BROWSER_CONCURRENCY_LIMIT=1
- KB_CHAT_SESSION_LOCK_TTL=600
- KB_CHAT_GLOBAL_SLOT_TTL=600
- KB_CHAT_QUEUE_ACTIVE_TTL=600

It also clears stale chat queue and lock state in Redis after the stack is brought up, so an old session cannot block the first chat request after install.

OpenClaw host nginx provisioning is opt-in. The installer will only write /etc/nginx/sites-available/openclaw-https and reload nginx if you pass --configure-openclaw-nginx. You can combine it with:

- --openclaw-nginx-listen-ip
- --openclaw-nginx-listen-port
- --openclaw-nginx-backend-host
- --openclaw-nginx-backend-port

When OpenClaw is installed on the same host, the installer normalizes the gateway defaults away from 127.0.0.1:18789 and uses the local host IP with port 18790 unless you explicitly override it.

The installer writes a release-specific config overlay and starts a release-isolated Docker Compose stack.
EOF
}

write_release_dockerfile() {
  cat > "$RUNTIME_DIR/Dockerfile.release" <<'EOF'
FROM python:3.12-slim

WORKDIR /opt/knowledge-base/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    poppler-utils \
    ca-certificates \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./

RUN mkdir -p /opt/knowledge-base/runtime/openclaw \
    && mkdir -p /opt/knowledge-base/runtime/logs \
    && mkdir -p /home/da40_ai_gb10 \
    && ln -sfn /opt/knowledge-base/app /home/da40_ai_gb10/knowledge-base \
    && ln -sfn /opt/knowledge-base/runtime/openclaw /home/da40_ai_gb10/.openclaw

ENV PYTHONPATH=/opt/knowledge-base/app
ENV PYTHONUNBUFFERED=1
ENV OPENCLAW_HOME=/opt/knowledge-base/runtime/openclaw
ENV KB_RELEASE_MODE=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
EOF
}

write_compose_file() {
  cat > "$RUNTIME_DIR/docker-compose.yml" <<'EOF'
name: ${KB_COMPOSE_PROJECT}

services:
  redis:
    image: redis:${KB_REDIS_IMAGE_TAG}
    restart: unless-stopped
    volumes:
      - kb_release_redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  neo4j:
    image: neo4j:${KB_NEO4J_IMAGE_TAG}
    restart: unless-stopped
    environment:
      NEO4J_AUTH: neo4j/${KB_NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - kb_release_neo4j_data:/data
      - kb_release_neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "${KB_NEO4J_PASSWORD}", "RETURN 1"]
      interval: 30s
      timeout: 10s
      retries: 5

  qdrant:
    image: qdrant/qdrant:${KB_QDRANT_IMAGE_TAG}
    restart: unless-stopped
    volumes:
      - kb_release_qdrant_data:/qdrant/storage

  web:
    build:
      context: ..
      dockerfile: runtime/Dockerfile.release
    restart: unless-stopped
    environment:
      OPENCLAW_HOME: /opt/knowledge-base/runtime/openclaw
      OPENCLAW_GATEWAY_HOST: ${KB_OPENCLAW_GATEWAY_HOST}
      OPENCLAW_GATEWAY_PORT: ${KB_OPENCLAW_GATEWAY_PORT}
      OPENCLAW_GATEWAY_WS_URL: ${KB_OPENCLAW_GATEWAY_WS_URL}
      OPENCLAW_CHAT_SESSION_KEY: ${KB_OPENCLAW_SESSION_KEY}
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: ${KB_NEO4J_PASSWORD}
      QDRANT_URL: http://qdrant:6333
      KB_INGEST_UPLOAD_ROOT: /opt/knowledge-base/app/data/uploads
      CHAT_GLOBAL_CONCURRENCY_LIMIT: ${KB_CHAT_GLOBAL_CONCURRENCY_LIMIT}
      CHAT_BROWSER_CONCURRENCY_LIMIT: ${KB_CHAT_BROWSER_CONCURRENCY_LIMIT}
      CHAT_SESSION_LOCK_TTL: ${KB_CHAT_SESSION_LOCK_TTL}
      CHAT_GLOBAL_SLOT_TTL: ${KB_CHAT_GLOBAL_SLOT_TTL}
      CHAT_QUEUE_ACTIVE_TTL: ${KB_CHAT_QUEUE_ACTIVE_TTL}
      LLM_MODEL: ${KB_LLM_MODEL}
      KB_RELEASE_MODE: "1"
    volumes:
      - ../app/config:/opt/knowledge-base/app/config
      - ../app/data:/opt/knowledge-base/app/data
      - ../runtime/openclaw:/opt/knowledge-base/runtime/openclaw
    depends_on:
      redis:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      qdrant:
        condition: service_started
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${KB_FASTAPI_WORKERS}

  celery_search_worker:
    build:
      context: ..
      dockerfile: runtime/Dockerfile.release
    restart: unless-stopped
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: ${KB_NEO4J_PASSWORD}
      QDRANT_URL: http://qdrant:6333
      KB_INGEST_UPLOAD_ROOT: /opt/knowledge-base/app/data/uploads
      KB_RELEASE_MODE: "1"
    volumes:
      - ../app/config:/opt/knowledge-base/app/config
      - ../app/data:/opt/knowledge-base/app/data
      - ../runtime/openclaw:/opt/knowledge-base/runtime/openclaw
    depends_on:
      redis:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      qdrant:
        condition: service_started
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=${KB_CELERY_SEARCH_CONCURRENCY} -Q search

  celery_ingest_worker:
    build:
      context: ..
      dockerfile: runtime/Dockerfile.release
    restart: unless-stopped
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: ${KB_NEO4J_PASSWORD}
      QDRANT_URL: http://qdrant:6333
      KB_INGEST_UPLOAD_ROOT: /opt/knowledge-base/app/data/uploads
      KB_RELEASE_MODE: "1"
    volumes:
      - ../app/config:/opt/knowledge-base/app/config
      - ../app/data:/opt/knowledge-base/app/data
      - ../runtime/openclaw:/opt/knowledge-base/runtime/openclaw
    depends_on:
      redis:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      qdrant:
        condition: service_started
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=${KB_CELERY_INGEST_CONCURRENCY} -Q ingest

  celery_beat:
    build:
      context: ..
      dockerfile: runtime/Dockerfile.release
    restart: unless-stopped
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: ${KB_NEO4J_PASSWORD}
      QDRANT_URL: http://qdrant:6333
      KB_INGEST_UPLOAD_ROOT: /opt/knowledge-base/app/data/uploads
      KB_RELEASE_MODE: "1"
    volumes:
      - ../app/config:/opt/knowledge-base/app/config
      - ../app/data:/opt/knowledge-base/app/data
      - ../runtime/openclaw:/opt/knowledge-base/runtime/openclaw
    depends_on:
      redis:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      qdrant:
        condition: service_started
    command: celery -A src.web_api.tasks:celery_app beat --loglevel=info

  nginx:
    image: nginx:${KB_NGINX_IMAGE_TAG}
    restart: unless-stopped
    ports:
      - "${KB_WEB_HTTPS_PORT}:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend:/usr/share/nginx/html:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      web:
        condition: service_started

volumes:
  kb_release_redis_data:
  kb_release_neo4j_data:
  kb_release_neo4j_logs:
  kb_release_qdrant_data:
EOF
}

write_nginx_conf() {
  cp "$PROJECT_ROOT/nginx.conf" "$RUNTIME_DIR/nginx.conf"
}

build_frontend_runtime() {
  require_cmd npm

  log "installing frontend dependencies"
  npm --prefix "$APP_DIR/frontend" ci --silent

  log "building frontend runtime"
  KB_FRONTEND_BUILD_DIR="$RUNTIME_DIR/frontend" npm --prefix "$APP_DIR/frontend" run build

  if [[ ! -f "$RUNTIME_DIR/frontend/index.html" ]]; then
    printf '[release] frontend build output is missing: %s\n' "$RUNTIME_DIR/frontend/index.html" >&2
    exit 1
  fi
  cp "$APP_DIR/frontend/chat.html" "$RUNTIME_DIR/frontend/chat.html"
  if [[ -f "$APP_DIR/frontend/lib/marked.min.js" || -f "$APP_DIR/frontend/lib/compare-rules.js" ]]; then
    mkdir -p "$RUNTIME_DIR/frontend/lib"
    [[ ! -f "$APP_DIR/frontend/lib/marked.min.js" ]] || cp "$APP_DIR/frontend/lib/marked.min.js" "$RUNTIME_DIR/frontend/lib/marked.min.js"
    [[ ! -f "$APP_DIR/frontend/lib/compare-rules.js" ]] || cp "$APP_DIR/frontend/lib/compare-rules.js" "$RUNTIME_DIR/frontend/lib/compare-rules.js"
  fi
}

write_install_script() {
  cat > "$STAGE_ROOT/install.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail

IFS=\$'\n\t'

PACKAGE_FORMAT_VERSION="$package_format_version"
PACKAGE_RELEASE_VERSION="$release_version"
PACKAGE_RELEASE_ID="$release_id"
PACKAGE_RELEASE_CHANNEL="$release_channel"
PACKAGE_GIT_COMMIT="$git_sha"
PACKAGE_CREATED_AT="$stamp"

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Interactive mode is the default. Press Enter to keep the suggested value.

Options:
  --install-root PATH
  --project-name NAME
  --web-port PORT
  --neo4j-password PASSWORD
  --ollama-base-url URL
  --openclaw-gateway-host HOST
  --openclaw-gateway-port PORT
  --openclaw-gateway-ws-url URL
  --openclaw-session-key KEY
  --openclaw-device-id ID
  --openclaw-device-token TOKEN
  --openclaw-gateway-auth-token TOKEN
  --data-bundle PATH
  --openclaw-bundle PATH
  --configure-openclaw-nginx
  --openclaw-nginx-listen-ip IP
  --openclaw-nginx-listen-port PORT
  --openclaw-nginx-backend-host HOST
  --openclaw-nginx-backend-port PORT
  --auto-install-deps
  --check-only
  --offline
  --non-interactive
  --force
  -h, --help
USAGE
}

log() { printf '[install] %s\n' "\$*"; }
warn() { printf '[install] warning: %s\n' "\$*" >&2; }
die() { printf '[install] error: %s\n' "\$*" >&2; exit 1; }

require_cmd() {
  if ! command -v "\$1" >/dev/null 2>&1; then
    die "Required command not found: \$1"
  fi
}

preflight_check_tool() {
  local label="\$1"
  local required="\$2"
  local status="OK"
  local detail="available"

  if ! command -v "\$label" >/dev/null 2>&1; then
    status="MISSING"
    detail="command not found"
  fi

  if [[ "\$label" == "docker" && "\$status" == "OK" ]]; then
    if ! docker info >/dev/null 2>&1; then
      status="MISSING"
      detail="installed but daemon is not running"
    fi
  fi

  if [[ "\$label" == "docker-compose-plugin" && "\$status" == "OK" ]]; then
    if ! docker compose version >/dev/null 2>&1; then
      status="MISSING"
      detail="docker compose plugin not available"
    fi
  fi

  printf '  %-24s %-8s %s\n' "\$required" "\$status" "\$detail"
  [[ "\$status" == "OK" ]]
}

scan_preflight() {
  PRECHECK_MISSING_REQUIRED=()
  PRECHECK_MISSING_OPTIONAL=()

  printf '\nPreflight check:\n'
  printf '  %-24s %-8s %s\n' "Component" "Status" "Details"
  preflight_check_tool docker "Docker"
  if [[ \$? -ne 0 ]]; then PRECHECK_MISSING_REQUIRED+=("docker"); fi

  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      printf '  %-24s %-8s %s\n' "Docker Compose" "OK" "available"
    else
      printf '  %-24s %-8s %s\n' "Docker Compose" "MISSING" "plugin not available"
      PRECHECK_MISSING_REQUIRED+=("docker-compose-plugin")
    fi
  else
    printf '  %-24s %-8s %s\n' "Docker Compose" "MISSING" "depends on Docker CLI"
    PRECHECK_MISSING_REQUIRED+=("docker-compose-plugin")
  fi

  preflight_check_tool tar "tar"
  if [[ \$? -ne 0 ]]; then PRECHECK_MISSING_REQUIRED+=("tar"); fi

  preflight_check_tool curl "curl"
  if [[ \$? -ne 0 ]]; then PRECHECK_MISSING_REQUIRED+=("curl"); fi

  preflight_check_tool openssl "openssl"
  if [[ \$? -ne 0 ]]; then PRECHECK_MISSING_REQUIRED+=("openssl"); fi

  if command -v rsync >/dev/null 2>&1; then
    printf '  %-24s %-8s %s\n' "rsync" "OK" "optional"
  else
    printf '  %-24s %-8s %s\n' "rsync" "MISSING" "optional; cp fallback will be used"
    PRECHECK_MISSING_OPTIONAL+=("rsync")
  fi

  if (( \${#PRECHECK_MISSING_REQUIRED[@]} > 0 )); then
    return 1
  fi
  return 0
}

attempt_auto_install_deps() {
  local missing_packages=()
  local sudo_cmd=()
  local can_use_apt=0

  if ! command -v apt-get >/dev/null 2>&1; then
    warn "apt-get not found; cannot auto-install missing dependencies."
    return 1
  fi

  can_use_apt=1
  if [[ \$EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    else
      warn "sudo not found; cannot auto-install missing dependencies without root."
      return 1
    fi
  fi

  if ! command -v docker >/dev/null 2>&1; then
    missing_packages+=(docker.io docker-compose-plugin)
  elif ! docker compose version >/dev/null 2>&1; then
    missing_packages+=(docker-compose-plugin)
  fi

  if ! command -v tar >/dev/null 2>&1; then
    missing_packages+=(tar)
  fi
  if ! command -v curl >/dev/null 2>&1; then
    missing_packages+=(curl)
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    missing_packages+=(openssl)
  fi
  if ! command -v rsync >/dev/null 2>&1; then
    missing_packages+=(rsync)
  fi

  if (( can_use_apt == 0 || \${#missing_packages[@]} == 0 )); then
    return 0
  fi

  log "Attempting to install missing packages: \${missing_packages[*]}"
  "\${sudo_cmd[@]}" apt-get update
  DEBIAN_FRONTEND=noninteractive "\${sudo_cmd[@]}" apt-get install -y "\${missing_packages[@]}"
}

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    od -An -N16 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

is_tty() {
  [[ -t 0 && -t 1 ]]
}

prompt_value() {
  local label="\$1"
  local default_value="\${2:-}"
  local reply=""
  if is_tty; then
    if [[ -n "\$default_value" ]]; then
      read -r -p "\$label [\$default_value]: " reply
    else
      read -r -p "\$label: " reply
    fi
  fi
  printf '%s' "\${reply:-\$default_value}"
}

prompt_secret() {
  local label="\$1"
  local default_note="\${2:-auto-generate}"
  local reply=""
  if is_tty; then
    read -r -p "\$label [\$default_note]: " reply
  fi
  printf '%s' "\$reply"
}

prompt_yes_no() {
  local label="\$1"
  local default_answer="\${2:-Y}"
  local reply=""
  if is_tty; then
    read -r -p "\$label [\${default_answer}/\${default_answer,,}]: " reply
  fi
  reply="\${reply:-\$default_answer}"
  case "\${reply,,}" in
    y|yes) return 0 ;;
    n|no) return 1 ;;
    *) return 0 ;;
  esac
}

load_env_file() {
  local file="\$1"
  [[ -f "\$file" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  source "\$file"
  set +a
}

ensure_dir() {
  mkdir -p "\$1"
}

sync_tree() {
  local source_dir="\$1"
  local target_dir="\$2"
  shift 2
  ensure_dir "\$target_dir"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "\$@" "\$source_dir"/ "\$target_dir"/
  else
    cp -a "\$source_dir"/. "\$target_dir"/
  fi
}

restore_data_bundle() {
  local bundle_path="\$1"
  local target_data_dir="\$2"
  local target_config_dir="\$3"
  local tmp_dir
  tmp_dir="\$(mktemp -d)"
  if [[ -d "\$bundle_path" ]]; then
    if command -v rsync >/dev/null 2>&1; then
      rsync -a "\$bundle_path"/ "\$tmp_dir"/
    else
      cp -a "\$bundle_path"/. "\$tmp_dir"/
    fi
  else
    tar -xzf "\$bundle_path" -C "\$tmp_dir"
  fi
  if [[ -d "\$tmp_dir/data" ]]; then
    ensure_dir "\$target_data_dir"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a "\$tmp_dir/data"/ "\$target_data_dir"/
    else
      cp -a "\$tmp_dir/data"/. "\$target_data_dir"/
    fi
  fi
  if [[ -f "\$tmp_dir/config/config.yaml" ]]; then
    ensure_dir "\$target_config_dir"
    cp "\$tmp_dir/config/config.yaml" "\$target_config_dir/config.yaml"
  fi
  rm -rf "\$tmp_dir"
}

restore_openclaw_bundle() {
  local bundle_path="\$1"
  local target_dir="\$2"
  local tmp_dir
  tmp_dir="\$(mktemp -d)"
  if [[ -d "\$bundle_path" ]]; then
    if command -v rsync >/dev/null 2>&1; then
      rsync -a "\$bundle_path"/ "\$tmp_dir"/
    else
      cp -a "\$bundle_path"/. "\$tmp_dir"/
    fi
  else
    tar -xzf "\$bundle_path" -C "\$tmp_dir"
  fi
  if [[ -d "\$tmp_dir/identity" ]]; then
    ensure_dir "\$target_dir/identity"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a "\$tmp_dir/identity"/ "\$target_dir/identity"/
    else
      cp -a "\$tmp_dir/identity"/. "\$target_dir/identity"/
    fi
  fi
  if [[ -d "\$tmp_dir/workspace" ]]; then
    ensure_dir "\$target_dir/workspace"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a "\$tmp_dir/workspace"/ "\$target_dir/workspace"/
    else
      cp -a "\$tmp_dir/workspace"/. "\$target_dir/workspace"/
    fi
  fi
  if [[ -f "\$tmp_dir/openclaw.json" ]]; then
    cp "\$tmp_dir/openclaw.json" "\$target_dir/openclaw.json"
  fi
  rm -rf "\$tmp_dir"
}

sync_host_openclaw_identity() {
  local target_root="\$1"
  local target_identity="\$target_root/runtime/openclaw/identity"
  local host_identity_dir="\${OPENCLAW_SOURCE_IDENTITY_DIR:-\$HOME/.openclaw/identity}"
  local host_device_json="\$host_identity_dir/device.json"
  local host_device_auth="\$host_identity_dir/device-auth.json"
  local target_device_json="\$target_identity/device.json"

  if [[ ! -f "\$host_device_json" ]]; then
    warn "OpenClaw host identity not found at \$host_device_json; skip identity sync."
    return 0
  fi

  if [[ -f "\$target_device_json" ]] && ! grep -Eq '"privateKeyPem": *""|"publicKeyPem": *""' "\$target_device_json"; then
    log "OpenClaw identity already populated; skip host sync."
    return 0
  fi

  ensure_dir "\$target_identity"
  cp -f "\$host_device_json" "\$target_device_json"
  if [[ -f "\$host_device_auth" ]]; then
    cp -f "\$host_device_auth" "\$target_identity/device-auth.json"
  fi
  log "Imported OpenClaw identity from \$host_identity_dir"
}

write_install_state() {
  local target_root="\$1"
  local mode="\$2"
  local previous_version="\$3"
  cat > "\$target_root/install-state.env" <<STATEEOF
KB_RELEASE_FORMAT_VERSION=$package_format_version
KB_RELEASE_VERSION=$release_version
KB_RELEASE_ID=$release_id
KB_RELEASE_CHANNEL=$release_channel
KB_GIT_COMMIT=$git_sha
KB_CREATED_AT=$stamp
KB_INSTALL_MODE=\$mode
KB_PREVIOUS_RELEASE_VERSION=\$previous_version
KB_INSTALL_ROOT=\$INSTALL_ROOT
KB_COMPOSE_PROJECT=\$PROJECT_NAME
KB_WEB_HTTPS_PORT=\$WEB_PORT
KB_NEO4J_PASSWORD=\$NEO4J_PASSWORD
KB_OLLAMA_BASE_URL=\$OLLAMA_BASE_URL
KB_OPENCLAW_GATEWAY_HOST=\$OPENCLAW_GATEWAY_HOST
KB_OPENCLAW_GATEWAY_PORT=\$OPENCLAW_GATEWAY_PORT
KB_OPENCLAW_GATEWAY_WS_URL=\$OPENCLAW_GATEWAY_WS_URL
KB_OPENCLAW_SESSION_KEY=\$OPENCLAW_SESSION_KEY
KB_OPENCLAW_DEVICE_ID=\$OPENCLAW_DEVICE_ID
KB_OPENCLAW_DEVICE_TOKEN=\$OPENCLAW_DEVICE_TOKEN
KB_OPENCLAW_GATEWAY_AUTH_TOKEN=\$OPENCLAW_GATEWAY_AUTH_TOKEN
KB_CHAT_GLOBAL_CONCURRENCY_LIMIT=\$KB_CHAT_GLOBAL_CONCURRENCY_LIMIT
KB_CHAT_BROWSER_CONCURRENCY_LIMIT=\$KB_CHAT_BROWSER_CONCURRENCY_LIMIT
KB_CHAT_SESSION_LOCK_TTL=\$KB_CHAT_SESSION_LOCK_TTL
KB_CHAT_GLOBAL_SLOT_TTL=\$KB_CHAT_GLOBAL_SLOT_TTL
KB_CHAT_QUEUE_ACTIVE_TTL=\$KB_CHAT_QUEUE_ACTIVE_TTL
KB_OPENCLAW_NGINX_ENABLED=\${KB_OPENCLAW_NGINX_ENABLED:-0}
KB_OPENCLAW_NGINX_LISTEN_IP=\${KB_OPENCLAW_NGINX_LISTEN_IP:-}
KB_OPENCLAW_NGINX_LISTEN_PORT=\${KB_OPENCLAW_NGINX_LISTEN_PORT:-18789}
KB_OPENCLAW_NGINX_BACKEND_HOST=\${KB_OPENCLAW_NGINX_BACKEND_HOST:-127.0.0.1}
KB_OPENCLAW_NGINX_BACKEND_PORT=\${KB_OPENCLAW_NGINX_BACKEND_PORT:-18790}
STATEEOF
}

write_release_info() {
  local target_root="\$1"
  cat > "\$target_root/release-info.json" <<INFOEOF
{
  "format_version": "$package_format_version",
  "release_version": "$release_version",
  "release_id": "$release_id",
  "release_channel": "$release_channel",
  "git_commit": "$git_sha",
  "created_at": "$stamp",
  "package_name": "$PACKAGE_NAME"
}
INFOEOF
}

backup_before_upgrade() {
  local target_root="\$1"
  local backup_root="\$target_root/backups/upgrade-\$(date +%Y%m%d_%H%M%S)"
  ensure_dir "\$backup_root"
  [[ -f "\$target_root/.env" ]] && cp "\$target_root/.env" "\$backup_root/.env"
  [[ -f "\$target_root/install-state.env" ]] && cp "\$target_root/install-state.env" "\$backup_root/install-state.env"
  [[ -f "\$target_root/app/config/config.yaml" ]] && cp "\$target_root/app/config/config.yaml" "\$backup_root/config.yaml"
  if [[ -d "\$target_root/runtime/openclaw" ]]; then
    if command -v tar >/dev/null 2>&1; then
      tar -czf "\$backup_root/openclaw.tar.gz" -C "\$target_root/runtime" openclaw
    fi
  fi
  log "upgrade backup created at \$backup_root"
}

reset_chat_runtime_state() {
  local lua_script
  lua_script="\$(cat <<'LUA'
local patterns = {
  "kb:chat:queue:req:*",
  "kb:chat:session_lock:*",
  "kb:chat:browser_active:*",
}

for _, pattern in ipairs(patterns) do
  local cursor = "0"
  repeat
    local result = redis.call("SCAN", cursor, "MATCH", pattern, "COUNT", 1000)
    cursor = result[1]
    local keys = result[2]
    if keys and #keys > 0 then
      redis.call("DEL", unpack(keys))
    end
  until cursor == "0"
end

redis.call("DEL", "kb:chat:queue", "kb:chat:queue:seq", "kb:chat:queue:active")
return 1
LUA
)"

  (
    cd "\$INSTALL_ROOT"
    for _ in \$(seq 1 12); do
      if docker compose --env-file .env -f runtime/docker-compose.yml exec -T redis redis-cli ping >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
    docker compose --env-file .env -f runtime/docker-compose.yml exec -T redis redis-cli --raw EVAL "\$lua_script" 0 >/dev/null 2>&1 || true
  )
}

detect_primary_ip() {
  if command -v hostname >/dev/null 2>&1; then
    local ip
    ip="\$(hostname -I 2>/dev/null | awk '{print \$1}' | tr -d '[:space:]')"
    if [[ -n "\$ip" ]]; then
      printf '%s' "\$ip"
      return 0
    fi
  fi
  printf '%s' "127.0.0.1"
}

configure_openclaw_host_nginx() {
  if [[ "\${OPENCLAW_NGINX_ENABLED:-0}" != "1" ]]; then
    return 0
  fi

  local listen_ip="\${OPENCLAW_NGINX_LISTEN_IP:-}"
  local listen_port="\${OPENCLAW_NGINX_LISTEN_PORT:-18789}"
  local backend_host="\${OPENCLAW_NGINX_BACKEND_HOST:-127.0.0.1}"
  local backend_port="\${OPENCLAW_NGINX_BACKEND_PORT:-18790}"
  local server_name="\${listen_ip:-}"
  local sudo_cmd=()
  local site_available="/etc/nginx/sites-available/openclaw-https"
  local site_enabled="/etc/nginx/sites-enabled/openclaw-https"
  local backup_root="\$INSTALL_ROOT/backups/openclaw-nginx-\$(date +%Y%m%d_%H%M%S)"
  local temp_conf

  if [[ -z "\$listen_ip" ]]; then
    listen_ip="\$(detect_primary_ip)"
  fi
  if [[ -z "\$server_name" ]]; then
    server_name="\$listen_ip"
  fi

  if [[ \$EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    else
      warn "sudo not available; cannot configure host nginx for OpenClaw."
      return 1
    fi
  fi

  if ! command -v nginx >/dev/null 2>&1; then
    warn "nginx not found; cannot configure host nginx for OpenClaw."
    return 1
  fi

  ensure_dir "\$backup_root"
  if "\${sudo_cmd[@]}" test -f "\$site_available"; then
    "\${sudo_cmd[@]}" cp -f "\$site_available" "\$backup_root/openclaw-https"
  fi

  temp_conf="\$(mktemp)"
  cat > "\$temp_conf" <<NGINXEOF
server {
    listen \${listen_ip}:\${listen_port} ssl;
    server_name \${server_name};

    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;

    location / {
        proxy_pass http://\${backend_host}:\${backend_port};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
NGINXEOF

  "\${sudo_cmd[@]}" install -d -m 0755 /etc/nginx/sites-available
  "\${sudo_cmd[@]}" install -d -m 0755 /etc/nginx/sites-enabled
  "\${sudo_cmd[@]}" install -m 0644 "\$temp_conf" "\$site_available"
  "\${sudo_cmd[@]}" ln -sfn "\$site_available" "\$site_enabled"
  rm -f "\$temp_conf"

  if ! "\${sudo_cmd[@]}" nginx -t; then
    warn "nginx configuration test failed for OpenClaw host site."
    return 1
  fi

  if command -v systemctl >/dev/null 2>&1; then
    if ! "\${sudo_cmd[@]}" systemctl reload nginx; then
      warn "Failed to reload nginx after OpenClaw host site update."
      return 1
    fi
  else
    if ! "\${sudo_cmd[@]}" nginx -s reload; then
      warn "Failed to reload nginx after OpenClaw host site update."
      return 1
    fi
  fi

  log "Configured host nginx for OpenClaw at https://\${listen_ip}:\${listen_port}"
  return 0
}

show_summary() {
  cat <<SUMMARY

Installation summary:
  Mode:                 \$MODE
  Install root:         \$INSTALL_ROOT
  Project name:         \$PROJECT_NAME
  Web port:             \$WEB_PORT
  Neo4j password:       <set>
  Ollama base URL:      \$OLLAMA_BASE_URL
  OpenClaw gateway:     \$OPENCLAW_GATEWAY_WS_URL
  Chat concurrency:     \$KB_CHAT_GLOBAL_CONCURRENCY_LIMIT
  Chat lock TTL:        \$KB_CHAT_SESSION_LOCK_TTL
  Host nginx:           \${OPENCLAW_NGINX_ENABLED:-0} (\${OPENCLAW_NGINX_LISTEN_IP:-auto}:\${OPENCLAW_NGINX_LISTEN_PORT:-18789} -> \${OPENCLAW_NGINX_BACKEND_HOST:-127.0.0.1}:\${OPENCLAW_NGINX_BACKEND_PORT:-18790})
  Data bundle:          \${DATA_BUNDLE:-<none>}
  OpenClaw bundle:      \${OPENCLAW_BUNDLE:-<none>}
SUMMARY
}

write_app_overlay() {
  local target_root="\$1"
  ensure_dir "\$target_root/app/config"
  cat > "\$target_root/app/config/config.yaml" <<CONFIGEOF
llm_provider: "ollama"
llm_model: "\${KB_LLM_MODEL:-qwen3-coder-next}"

neo4j_uri: "bolt://neo4j:7687"
neo4j_user: "neo4j"
neo4j_password: "\$NEO4J_PASSWORD"

data:
  base: "/opt/knowledge-base/app/data"

embedding_model: "sentence-transformers/all-MiniLM-L6-v2"

search:
  basic_top_k: 3
  deep_top_k: 6
  auto_mode_keywords:
    - "為什麼"
    - "如何"
    - "怎麼"
    - "比較"
    - "關係"
    - "原因"
    - "哪些"

ollama:
  instances:
    - "\$OLLAMA_BASE_URL"
  model: "\${KB_LLM_MODEL:-qwen3-coder-next}"
  num_predict: 4096
  strategy: "round_robin"
  timeout: 300

qdrant:
  url: "http://qdrant:6333"

openclaw:
  gateway_host: "\$OPENCLAW_GATEWAY_HOST"
  gateway_port: \$OPENCLAW_GATEWAY_PORT
  gateway_ws_url: "\$OPENCLAW_GATEWAY_WS_URL"
CONFIGEOF
}

write_env_file() {
  local target_root="\$1"
  cat > "\$target_root/.env" <<ENVEOF
KB_COMPOSE_PROJECT=\$PROJECT_NAME
KB_WEB_HTTPS_PORT=\$WEB_PORT
KB_NEO4J_PASSWORD=\$NEO4J_PASSWORD
KB_NEO4J_IMAGE_TAG=\${KB_NEO4J_IMAGE_TAG:-latest}
KB_REDIS_IMAGE_TAG=\${KB_REDIS_IMAGE_TAG:-7-alpine}
KB_QDRANT_IMAGE_TAG=\${KB_QDRANT_IMAGE_TAG:-latest}
KB_NGINX_IMAGE_TAG=\${KB_NGINX_IMAGE_TAG:-alpine}
KB_LLM_MODEL=\${KB_LLM_MODEL:-qwen3-coder-next}
KB_FASTAPI_WORKERS=\${KB_FASTAPI_WORKERS:-2}
KB_CELERY_SEARCH_CONCURRENCY=\${KB_CELERY_SEARCH_CONCURRENCY:-2}
KB_CELERY_INGEST_CONCURRENCY=\${KB_CELERY_INGEST_CONCURRENCY:-1}
KB_CHAT_GLOBAL_CONCURRENCY_LIMIT=\${KB_CHAT_GLOBAL_CONCURRENCY_LIMIT:-2}
KB_CHAT_BROWSER_CONCURRENCY_LIMIT=\${KB_CHAT_BROWSER_CONCURRENCY_LIMIT:-1}
KB_CHAT_SESSION_LOCK_TTL=\${KB_CHAT_SESSION_LOCK_TTL:-600}
KB_CHAT_GLOBAL_SLOT_TTL=\${KB_CHAT_GLOBAL_SLOT_TTL:-600}
KB_CHAT_QUEUE_ACTIVE_TTL=\${KB_CHAT_QUEUE_ACTIVE_TTL:-600}
KB_OPENCLAW_GATEWAY_HOST=\$OPENCLAW_GATEWAY_HOST
KB_OPENCLAW_GATEWAY_PORT=\$OPENCLAW_GATEWAY_PORT
KB_OPENCLAW_GATEWAY_WS_URL=\$OPENCLAW_GATEWAY_WS_URL
KB_OPENCLAW_SESSION_KEY=\$OPENCLAW_SESSION_KEY
ENVEOF
}

write_openclaw_overlay() {
  local target_root="\$1"
  ensure_dir "\$target_root/runtime/openclaw/identity"
  ensure_dir "\$target_root/runtime/openclaw/workspace/memory"
  cat > "\$target_root/runtime/openclaw/identity/device.json" <<DEVICEEOF
{
  "deviceId": "\$OPENCLAW_DEVICE_ID",
  "privateKeyPem": "",
  "publicKeyPem": ""
}
DEVICEEOF
  cat > "\$target_root/runtime/openclaw/identity/device-auth.json" <<AUTHEOF
{
  "tokens": {
    "operator": {
      "token": "\$OPENCLAW_DEVICE_TOKEN",
      "scopes": [
        "operator.admin",
        "operator.approvals",
        "operator.pairing",
        "operator.read",
        "operator.talk.secrets",
        "operator.write"
      ]
    }
  }
}
AUTHEOF
  cat > "\$target_root/runtime/openclaw/openclaw.json" <<OPENCLAWEOF
{
  "gateway": {
    "port": \$OPENCLAW_GATEWAY_PORT,
    "auth": {
      "token": "\$OPENCLAW_GATEWAY_AUTH_TOKEN"
    }
  }
}
OPENCLAWEOF
  cat > "\$target_root/runtime/openclaw/workspace/memory/00-bootstrap.md" <<MEMEOF
# Bootstrap

sessionKey: \$OPENCLAW_SESSION_KEY
正式 Chat 網址: /chat.html?sessionKey=\$OPENCLAW_SESSION_KEY
MEMEOF
}

apply_chat_defaults() {
  if [[ -z "\${KB_CHAT_GLOBAL_CONCURRENCY_LIMIT:-}" || "\${KB_CHAT_GLOBAL_CONCURRENCY_LIMIT:-}" == "1" ]]; then
    KB_CHAT_GLOBAL_CONCURRENCY_LIMIT=2
  fi
  if [[ -z "\${KB_CHAT_BROWSER_CONCURRENCY_LIMIT:-}" ]]; then
    KB_CHAT_BROWSER_CONCURRENCY_LIMIT=1
  fi
  if [[ -z "\${KB_CHAT_SESSION_LOCK_TTL:-}" || "\${KB_CHAT_SESSION_LOCK_TTL:-}" == "1200" ]]; then
    KB_CHAT_SESSION_LOCK_TTL=600
  fi
  if [[ -z "\${KB_CHAT_GLOBAL_SLOT_TTL:-}" || "\${KB_CHAT_GLOBAL_SLOT_TTL:-}" == "1200" ]]; then
    KB_CHAT_GLOBAL_SLOT_TTL=600
  fi
  if [[ -z "\${KB_CHAT_QUEUE_ACTIVE_TTL:-}" || "\${KB_CHAT_QUEUE_ACTIVE_TTL:-}" == "1200" ]]; then
    KB_CHAT_QUEUE_ACTIVE_TTL=600
  fi
}

prepare_default_values() {
  local install_root="\${INSTALL_ROOT:-\$HOME/knowledge-base-onprem}"

  if [[ -f "\$install_root/install-state.env" ]]; then
    load_env_file "\$install_root/install-state.env"
    MODE="upgrade"
  elif [[ -f "\$install_root/.env" ]]; then
    load_env_file "\$install_root/.env"
    MODE="install"
  fi
}

normalize_openclaw_gateway_defaults() {
  local detected_host
  detected_host="\$(detect_primary_ip)"

  if [[ -z "\${OPENCLAW_GATEWAY_HOST:-}" || "\${OPENCLAW_GATEWAY_HOST:-}" == "127.0.0.1" ]]; then
    OPENCLAW_GATEWAY_HOST="\$detected_host"
  fi

  if [[ -z "\${OPENCLAW_GATEWAY_PORT:-}" || "\${OPENCLAW_GATEWAY_PORT:-}" == "18789" ]]; then
    OPENCLAW_GATEWAY_PORT="18790"
  fi

  if [[ -z "\${OPENCLAW_GATEWAY_WS_URL:-}" || "\${OPENCLAW_GATEWAY_WS_URL:-}" == "ws://127.0.0.1:18789/ws" || "\${OPENCLAW_GATEWAY_WS_URL:-}" == "ws://\${OPENCLAW_GATEWAY_HOST}:18789/ws" ]]; then
    OPENCLAW_GATEWAY_WS_URL="ws://\${OPENCLAW_GATEWAY_HOST}:\${OPENCLAW_GATEWAY_PORT}/ws"
  fi
}

create_certificate() {
  local cert_dir="\$1"
  ensure_dir "\$cert_dir"
  if [[ ! -f "\$cert_dir/cert.pem" || ! -f "\$cert_dir/key.pem" ]]; then
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -keyout "\$cert_dir/key.pem" \
      -out "\$cert_dir/cert.pem" \
      -subj "/CN=localhost" >/dev/null 2>&1
  fi
}

apply_upgrade_or_install() {
  local source_app="\$SCRIPT_DIR/app"
  local source_runtime="\$SCRIPT_DIR/runtime"
  ensure_dir "\$INSTALL_ROOT"
  ensure_dir "\$INSTALL_ROOT/app"
  ensure_dir "\$INSTALL_ROOT/runtime"
  ensure_dir "\$INSTALL_ROOT/app/data/raw"
  ensure_dir "\$INSTALL_ROOT/app/data/processed"
  ensure_dir "\$INSTALL_ROOT/app/data/assets"
  ensure_dir "\$INSTALL_ROOT/app/data/uploads"

  local app_excludes=(--exclude 'data/' --exclude 'config/config.yaml' --exclude 'frontend/node_modules/' --exclude 'frontend/build/' --exclude 'frontend/build2/' --exclude 'frontend/dist/' --exclude 'frontend/.vite/' --exclude 'frontend/.frontend-build-runtime-user/' --exclude 'frontend/.frontend-build-runtime-user8/' --exclude 'src/extract_entities.py.bak' --exclude 'src/web_api/tasks.py.bak' --exclude 'frontend/chat_draft*.html' --exclude 'frontend/ws-chat*.cjs')
  local runtime_excludes=(--exclude 'openclaw/' --exclude 'certs/')

  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete "\${app_excludes[@]}" "\$source_app"/ "\$INSTALL_ROOT/app"/
    rsync -a --delete "\${runtime_excludes[@]}" "\$source_runtime"/ "\$INSTALL_ROOT/runtime"/
  else
    cp -a "\$source_app"/. "\$INSTALL_ROOT/app"/
    cp -a "\$source_runtime"/. "\$INSTALL_ROOT/runtime"/
    rm -rf "\$INSTALL_ROOT/app/data"
    ensure_dir "\$INSTALL_ROOT/app/data/raw" "\$INSTALL_ROOT/app/data/processed" "\$INSTALL_ROOT/app/data/assets" "\$INSTALL_ROOT/app/data/uploads"
  fi

  cp "\$SCRIPT_DIR/app/config/config.yaml.example" "\$INSTALL_ROOT/app/config/config.yaml.example"
  cp "\$SCRIPT_DIR/runtime/nginx.conf" "\$INSTALL_ROOT/runtime/nginx.conf"
  if [[ ! -f "\$INSTALL_ROOT/runtime/frontend/index.html" ]]; then
    die "Frontend runtime build is missing: \$INSTALL_ROOT/runtime/frontend/index.html"
  fi
  create_certificate "\$INSTALL_ROOT/runtime/certs"
}

confirm_and_collect() {
  local detected_mode="\$1"
  local prev_release="\${KB_RELEASE_VERSION:-unknown}"
  if [[ "\$detected_mode" == "upgrade" ]]; then
    log "Existing installation detected at \$INSTALL_ROOT"
    log "Current installed version: \${KB_RELEASE_VERSION:-unknown}"
    log "This package version: \$PACKAGE_RELEASE_VERSION"
    if prompt_yes_no "Proceed with upgrade?" "Y"; then
      backup_before_upgrade "\$INSTALL_ROOT"
      UPGRADE_BACKED_UP=1
    else
      die "Upgrade cancelled."
    fi
  else
    log "Fresh installation mode"
  fi

  INSTALL_ROOT="\$(prompt_value 'Install root' "\${INSTALL_ROOT:-$HOME/knowledge-base-onprem}")"
  PROJECT_NAME="\$(prompt_value 'Compose project name' "\${PROJECT_NAME:-kb_onprem}")"
  WEB_PORT="\$(prompt_value 'HTTPS port' "\${WEB_PORT:-18443}")"

  local neo4j_default="\${KB_NEO4J_PASSWORD:-}"
  if [[ -z "\$neo4j_default" ]]; then
    NEO4J_PASSWORD="\$(prompt_secret 'Neo4j password (blank = auto-generate)' 'auto-generate')"
    if [[ -z "\$NEO4J_PASSWORD" ]]; then
      NEO4J_PASSWORD="\$(rand_hex)"
    fi
  else
    if prompt_yes_no "Keep existing Neo4j password?" "Y"; then
      NEO4J_PASSWORD="\$neo4j_default"
    else
      NEO4J_PASSWORD="\$(prompt_secret 'New Neo4j password (blank = auto-generate)' 'auto-generate')"
      [[ -z "\$NEO4J_PASSWORD" ]] && NEO4J_PASSWORD="\$(rand_hex)"
    fi
  fi

  OLLAMA_BASE_URL="\$(prompt_value 'Ollama base URL' "\${KB_OLLAMA_BASE_URL:-http://ollama:11434}")"
  OPENCLAW_GATEWAY_HOST="\$(prompt_value 'OpenClaw gateway host' "\${OPENCLAW_GATEWAY_HOST:-\$(detect_primary_ip)}")"
  OPENCLAW_GATEWAY_PORT="\$(prompt_value 'OpenClaw gateway port' "\${OPENCLAW_GATEWAY_PORT:-18790}")"

  if prompt_yes_no "Customize OpenClaw identity values?" "N"; then
    OPENCLAW_SESSION_KEY="\$(prompt_value 'OpenClaw session key' "\${KB_OPENCLAW_SESSION_KEY:-\$(rand_hex)}")"
    OPENCLAW_DEVICE_ID="\$(prompt_value 'OpenClaw device ID' "\${KB_OPENCLAW_DEVICE_ID:-kbrel-\$(rand_hex | cut -c1-12)}")"
    OPENCLAW_DEVICE_TOKEN="\$(prompt_value 'OpenClaw device token' "\${KB_OPENCLAW_DEVICE_TOKEN:-\$(rand_hex)}")"
    OPENCLAW_GATEWAY_AUTH_TOKEN="\$(prompt_value 'OpenClaw gateway auth token' "\${KB_OPENCLAW_GATEWAY_AUTH_TOKEN:-\$(rand_hex)}")"
  else
    OPENCLAW_SESSION_KEY="\${KB_OPENCLAW_SESSION_KEY:-\$(rand_hex)}"
    OPENCLAW_DEVICE_ID="\${KB_OPENCLAW_DEVICE_ID:-kbrel-\$(rand_hex | cut -c1-12)}"
    OPENCLAW_DEVICE_TOKEN="\${KB_OPENCLAW_DEVICE_TOKEN:-\$(rand_hex)}"
    OPENCLAW_GATEWAY_AUTH_TOKEN="\${KB_OPENCLAW_GATEWAY_AUTH_TOKEN:-\$(rand_hex)}"
  fi

  OPENCLAW_GATEWAY_WS_URL="\$(prompt_value 'OpenClaw gateway WS URL' "\${OPENCLAW_GATEWAY_WS_URL:-ws://\${OPENCLAW_GATEWAY_HOST}:\${OPENCLAW_GATEWAY_PORT}/ws}")"

  DATA_BUNDLE="\$(prompt_value 'Data bundle path (blank to skip)' "\${DATA_BUNDLE:-}")"
  OPENCLAW_BUNDLE="\$(prompt_value 'OpenClaw bundle path (blank to skip)' "\${OPENCLAW_BUNDLE:-}")"

  if ! prompt_yes_no "Continue with these settings?" "Y"; then
    die "Installation cancelled."
  fi
}

finalize_install() {
  local previous_release="\${KB_RELEASE_VERSION:-unknown}"
  write_app_overlay "\$INSTALL_ROOT"
  write_env_file "\$INSTALL_ROOT"
  write_openclaw_overlay "\$INSTALL_ROOT"
  write_install_state "\$INSTALL_ROOT" "\$MODE" "\$previous_release"
  write_release_info "\$INSTALL_ROOT"
}

run_compose() {
  (
    cd "\$INSTALL_ROOT"
    docker compose --env-file .env -f runtime/docker-compose.yml up -d --build
  )
}

health_check() {
  sleep 5
  if curl -k -fsS "https://127.0.0.1:\${WEB_PORT}/health" >/dev/null 2>&1; then
    log "Health check OK"
  else
    warn "Health check pending; inspect docker compose logs under \$INSTALL_ROOT"
  fi
}

main() {
  local non_interactive=0
  local auto_install_deps=0
  local check_only=0
  local offline_mode=0
  local UPGRADE_BACKED_UP=0
  local configure_openclaw_nginx=0
  DATA_BUNDLE=""
  OPENCLAW_BUNDLE=""
  MODE="install"

  while [[ \$# -gt 0 ]]; do
    case "\$1" in
      --install-root) INSTALL_ROOT="\$2"; shift 2 ;;
      --project-name) PROJECT_NAME="\$2"; shift 2 ;;
      --web-port) WEB_PORT="\$2"; shift 2 ;;
      --neo4j-password) NEO4J_PASSWORD="\$2"; shift 2 ;;
      --ollama-base-url) OLLAMA_BASE_URL="\$2"; shift 2 ;;
      --openclaw-gateway-host) OPENCLAW_GATEWAY_HOST="\$2"; shift 2 ;;
      --openclaw-gateway-port) OPENCLAW_GATEWAY_PORT="\$2"; shift 2 ;;
      --openclaw-gateway-ws-url) OPENCLAW_GATEWAY_WS_URL="\$2"; shift 2 ;;
      --openclaw-session-key) OPENCLAW_SESSION_KEY="\$2"; shift 2 ;;
      --openclaw-device-id) OPENCLAW_DEVICE_ID="\$2"; shift 2 ;;
      --openclaw-device-token) OPENCLAW_DEVICE_TOKEN="\$2"; shift 2 ;;
      --openclaw-gateway-auth-token) OPENCLAW_GATEWAY_AUTH_TOKEN="\$2"; shift 2 ;;
      --data-bundle) DATA_BUNDLE="\$2"; shift 2 ;;
      --openclaw-bundle) OPENCLAW_BUNDLE="\$2"; shift 2 ;;
      --configure-openclaw-nginx) configure_openclaw_nginx=1; shift ;;
      --openclaw-nginx-listen-ip) OPENCLAW_NGINX_LISTEN_IP="\$2"; shift 2 ;;
      --openclaw-nginx-listen-port) OPENCLAW_NGINX_LISTEN_PORT="\$2"; shift 2 ;;
      --openclaw-nginx-backend-host) OPENCLAW_NGINX_BACKEND_HOST="\$2"; shift 2 ;;
      --openclaw-nginx-backend-port) OPENCLAW_NGINX_BACKEND_PORT="\$2"; shift 2 ;;
      --auto-install-deps) auto_install_deps=1; shift ;;
      --check-only) check_only=1; shift ;;
      --offline) offline_mode=1; shift ;;
      --non-interactive) non_interactive=1; shift ;;
      --force) shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown option: \$1" ;;
    esac
  done

  if ! scan_preflight; then
    warn "One or more required dependencies are missing."
  fi

  if [[ "\$check_only" -eq 1 ]]; then
    printf '\nPreflight summary:\n'
    if (( \${#PRECHECK_MISSING_REQUIRED[@]} == 0 )); then
      printf '  All required components are available.\n'
      exit 0
    fi
    printf '  Missing required components:\n'
    for item in "\${PRECHECK_MISSING_REQUIRED[@]}"; do
      printf '    - %s\n' "\$item"
    done
    exit 1
  fi

  if [[ "\$offline_mode" -eq 1 ]]; then
    if [[ "\$auto_install_deps" -eq 1 ]]; then
      warn "--offline disables --auto-install-deps; skipping network-based remediation."
    fi
    if (( \${#PRECHECK_MISSING_REQUIRED[@]} > 0 )); then
      printf '\nOffline mode cannot continue with missing required components:\n'
      for item in "\${PRECHECK_MISSING_REQUIRED[@]}"; do
        printf '  - %s\n' "\$item"
      done
      die "Install prerequisite check failed in offline mode."
    fi
  elif [[ "\$auto_install_deps" -eq 1 ]]; then
    if ! attempt_auto_install_deps; then
      warn "Automatic dependency installation failed."
    fi
  elif [[ "\$non_interactive" -eq 0 ]] && is_tty; then
    if prompt_yes_no "Try automatic installation of missing dependencies where possible?" "Y"; then
      if ! attempt_auto_install_deps; then
        warn "Automatic dependency installation failed."
      fi
    fi
  fi

  if ! scan_preflight; then
    printf '\nMissing required components:\n'
    for item in "\${PRECHECK_MISSING_REQUIRED[@]}"; do
      printf '  - %s\n' "\$item"
    done
    if [[ "\$offline_mode" -eq 1 ]]; then
      die "Offline mode requires all prerequisites to be present."
    fi
    if [[ "\$non_interactive" -eq 1 || ! is_tty ]]; then
      die "Cannot continue until required dependencies are installed."
    fi
    if prompt_yes_no "Continue anyway and let the install fail later?" "N"; then
      warn "Continuing with missing dependencies at user request."
    else
      die "Installation cancelled."
    fi
  fi

  require_cmd docker
  require_cmd tar
  require_cmd curl
  require_cmd openssl

  if ! docker info >/dev/null 2>&1; then
    die "Docker is installed but not running."
  fi

  INSTALL_ROOT="\${INSTALL_ROOT:-\$HOME/knowledge-base-onprem}"
  prepare_default_values
  normalize_openclaw_gateway_defaults
  apply_chat_defaults

  if [[ "\$configure_openclaw_nginx" -eq 1 ]]; then
    OPENCLAW_NGINX_ENABLED=1
    KB_OPENCLAW_NGINX_ENABLED=1
    OPENCLAW_NGINX_LISTEN_IP="\${OPENCLAW_NGINX_LISTEN_IP:-\$(detect_primary_ip)}"
    OPENCLAW_NGINX_LISTEN_PORT="\${OPENCLAW_NGINX_LISTEN_PORT:-18789}"
    OPENCLAW_NGINX_BACKEND_HOST="\${OPENCLAW_NGINX_BACKEND_HOST:-127.0.0.1}"
    OPENCLAW_NGINX_BACKEND_PORT="\${OPENCLAW_NGINX_BACKEND_PORT:-18790}"
  else
    OPENCLAW_NGINX_ENABLED="\${KB_OPENCLAW_NGINX_ENABLED:-0}"
    KB_OPENCLAW_NGINX_ENABLED="\${KB_OPENCLAW_NGINX_ENABLED:-0}"
  fi

  if [[ "\$non_interactive" -eq 0 ]] && is_tty; then
    confirm_and_collect "\$MODE"
  else
    INSTALL_ROOT="\${INSTALL_ROOT:-\$HOME/knowledge-base-onprem}"
    PROJECT_NAME="\${PROJECT_NAME:-kb_onprem}"
    WEB_PORT="\${WEB_PORT:-18443}"
    OLLAMA_BASE_URL="\${OLLAMA_BASE_URL:-http://ollama:11434}"
    OPENCLAW_GATEWAY_HOST="\${OPENCLAW_GATEWAY_HOST:-\$(detect_primary_ip)}"
    OPENCLAW_GATEWAY_PORT="\${OPENCLAW_GATEWAY_PORT:-18790}"
    OPENCLAW_GATEWAY_WS_URL="\${OPENCLAW_GATEWAY_WS_URL:-ws://\${OPENCLAW_GATEWAY_HOST}:\${OPENCLAW_GATEWAY_PORT}/ws}"
    OPENCLAW_SESSION_KEY="\${OPENCLAW_SESSION_KEY:-\$(rand_hex)}"
    OPENCLAW_DEVICE_ID="\${OPENCLAW_DEVICE_ID:-kbrel-\$(rand_hex | cut -c1-12)}"
    OPENCLAW_DEVICE_TOKEN="\${OPENCLAW_DEVICE_TOKEN:-\$(rand_hex)}"
    OPENCLAW_GATEWAY_AUTH_TOKEN="\${OPENCLAW_GATEWAY_AUTH_TOKEN:-\$(rand_hex)}"
    DATA_BUNDLE="\${DATA_BUNDLE:-}"
    OPENCLAW_BUNDLE="\${OPENCLAW_BUNDLE:-}"
    if [[ "\$configure_openclaw_nginx" -eq 1 ]]; then
      OPENCLAW_NGINX_LISTEN_IP="\${OPENCLAW_NGINX_LISTEN_IP:-\$(detect_primary_ip)}"
      OPENCLAW_NGINX_LISTEN_PORT="\${OPENCLAW_NGINX_LISTEN_PORT:-18789}"
      OPENCLAW_NGINX_BACKEND_HOST="\${OPENCLAW_NGINX_BACKEND_HOST:-127.0.0.1}"
      OPENCLAW_NGINX_BACKEND_PORT="\${OPENCLAW_NGINX_BACKEND_PORT:-18790}"
    fi
    if [[ -z "\${NEO4J_PASSWORD:-}" ]]; then
      NEO4J_PASSWORD="\$(rand_hex)"
    fi
    if [[ "\$configure_openclaw_nginx" -eq 1 ]]; then
      OPENCLAW_NGINX_ENABLED=1
      KB_OPENCLAW_NGINX_ENABLED=1
      OPENCLAW_NGINX_LISTEN_IP="\${OPENCLAW_NGINX_LISTEN_IP:-\$(detect_primary_ip)}"
      OPENCLAW_NGINX_LISTEN_PORT="\${OPENCLAW_NGINX_LISTEN_PORT:-18789}"
      OPENCLAW_NGINX_BACKEND_HOST="\${OPENCLAW_NGINX_BACKEND_HOST:-127.0.0.1}"
      OPENCLAW_NGINX_BACKEND_PORT="\${OPENCLAW_NGINX_BACKEND_PORT:-18790}"
    fi
  fi

  ensure_dir "\$INSTALL_ROOT"
  if [[ -f "\$INSTALL_ROOT/install-state.env" ]]; then
    load_env_file "\$INSTALL_ROOT/install-state.env"
    MODE="upgrade"
  fi

  if [[ "\$MODE" == "upgrade" ]]; then
    if [[ "\$UPGRADE_BACKED_UP" -eq 0 ]]; then
      backup_before_upgrade "\$INSTALL_ROOT"
      UPGRADE_BACKED_UP=1
    fi
  fi

  finalize_install
  apply_upgrade_or_install
  if [[ -n "\$DATA_BUNDLE" ]]; then
    restore_data_bundle "\$DATA_BUNDLE" "\$INSTALL_ROOT/app/data" "\$INSTALL_ROOT/app/config"
  fi
  if [[ -n "\$OPENCLAW_BUNDLE" ]]; then
    restore_openclaw_bundle "\$OPENCLAW_BUNDLE" "\$INSTALL_ROOT/runtime/openclaw"
  fi
  sync_host_openclaw_identity "\$INSTALL_ROOT"
  run_compose
  reset_chat_runtime_state
  if ! configure_openclaw_host_nginx; then
    warn "OpenClaw host nginx configuration was requested but could not be completed."
  fi

  printf '\nInstallation completed.\n'
  printf '  Package version: %s\n' "\$PACKAGE_RELEASE_VERSION"
  printf '  Install root:    %s\n' "\$INSTALL_ROOT"
  printf '  Project name:    %s\n' "\$PROJECT_NAME"
  printf '  Web port:        %s\n' "\$WEB_PORT"
  printf '  Mode:            %s\n' "\$MODE"
  printf '  State file:      %s\n' "\$INSTALL_ROOT/install-state.env"
  printf '  Release info:    %s\n' "\$INSTALL_ROOT/release-info.json"
  health_check
}

main "\$@"
EOF
  chmod +x "$STAGE_ROOT/install.sh"
}

build_package() {
  mkdir -p "$DIST_ROOT"
  tar -czf "$PACKAGE_PATH" -C "$BUILD_ROOT" "knowledge-base-onprem-$release_id"
  sha256sum "$PACKAGE_PATH" > "$CHECKSUM_PATH"
}

main() {
  require_cmd git
  require_cmd tar
  require_cmd cp
  require_cmd find
  require_cmd openssl
  require_cmd curl

  log "preparing stage: $STAGE_ROOT"
  rm -rf "$STAGE_ROOT"
  mkdir -p "$APP_DIR" "$RUNTIME_DIR" "$DATA_DIR" "$CONFIG_DIR" "$DIST_ROOT"

  log "copying source bundle"
  copy_source_dir app "$APP_DIR"
  copy_source_dir src "$APP_DIR"
  copy_source_dir frontend "$APP_DIR"
  copy_source_dir requirements.txt "$APP_DIR"
  copy_source_dir nginx.conf "$APP_DIR"
  mkdir -p "$APP_DIR/config" "$APP_DIR/data/raw" "$APP_DIR/data/processed" "$APP_DIR/data/assets" "$APP_DIR/data/uploads"
  cp "$PROJECT_ROOT/config/config.yaml.example" "$APP_DIR/config/config.yaml.example"

  clean_release_artifacts
  write_manifest
  write_package_release_info
  write_readme
  write_release_dockerfile
  write_compose_file
  write_nginx_conf
  build_frontend_runtime
  clean_release_artifacts
  write_install_script
  build_package

  log "package ready: $PACKAGE_PATH"
  log "checksum: $CHECKSUM_PATH"
}

main "\$@"
